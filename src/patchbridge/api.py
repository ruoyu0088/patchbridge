from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .applying import (
    align_session_patch,
    apply_session,
    dry_run,
    recover_incomplete,
    revert_session,
)
from .archive import cleanup_tmp
from .config import AppConfig
from .errors import AppError
from .exporting import combined_patch, disk_diff, export_markdown
from .fsutil import read_text_file
from .mpatch import mpatch_version, resolve_mpatch
from .packing import build_bundle
from .profiles import (
    create_profile,
    delete_profile,
    delete_selection,
    list_profiles,
    load_profile,
    load_selection,
    save_selection,
    update_profile,
)
from .scanner import scan_project
from .scripting import run_session_script
from .sessions import SessionStore, utc_now

logger = logging.getLogger("patchbridge.api")


class ProjectBody(BaseModel):
    id: str | None = None
    name: str = ""
    root: str = ""
    mode: str = "exclude"
    rules: list[str] | str = Field(default_factory=list)
    raw: str | None = None


class SelectionBody(BaseModel):
    files: list[str] = Field(default_factory=list)


class PackBody(BaseModel):
    requirement: str
    files: list[str]
    title: str | None = None
    mode: str = "python"


class AnswerBody(BaseModel):
    answer: str


class CommitBody(BaseModel):
    commit_message: str


class PatchBody(BaseModel):
    content: str


class MergePatchesBody(BaseModel):
    patch_ids: list[str]


class AlignIndentBody(BaseModel):
    align_added: bool = True


class DryRunBody(BaseModel):
    patch_ids: list[str] | None = None
    persist: bool = True


class ApplyBody(BaseModel):
    patch_ids: list[str]
    confirm_hash_changes: list[str] = Field(default_factory=list)


class ScriptRunBody(BaseModel):
    script: str | None = None
    timeout_seconds: int | None = None


class RevertBody(BaseModel):
    confirm_hash_changes: bool = False


class ArchiveBody(BaseModel):
    confirm_active_apply: bool = False


class SettingsBody(BaseModel):
    large_file_bytes: int | None = None
    auto_archive_enabled: bool | None = None
    auto_archive_days: int | None = None
    prompt_template_path: str | None = None
    python_prompt_template_path: str | None = None
    backup_retention_days: int | None = None
    script_timeout_seconds: int | None = None
    script_max_output_chars: int | None = None
    diff_context_lines: int | None = None
    max_files: int | None = None
    max_bundle_bytes: int | None = None
    mpatch_path: str | None = None
    mpatch_fuzz_factor: float | None = None
    mpatch_timeout_seconds: int | None = None
    mpatch_repair_full_file_bytes: int | None = None
    mpatch_repair_context_lines: int | None = None


def ok(data: Any = None) -> dict[str, Any]:
    return {"ok": True, "data": data}


def create_api(config: AppConfig) -> FastAPI:
    store = SessionStore(config)
    auto_lock = threading.Lock()
    auto_state: dict[str, Any] = {
        "running": False,
        "session_id": None,
        "started_at": None,
        "finished_at": None,
        "success": None,
        "message": "",
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cleanup_tmp(config.tmp_dir)
        recover_incomplete(store)
        store.auto_archive()
        store.cleanup_backups()
        store.ensure_index()
        yield

    app = FastAPI(title="PatchBridge", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.store = store

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "error": exc.as_dict()},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": {
                    "code": "validation_error",
                    "message": "请求参数不合法",
                    "details": exc.errors(),
                },
            },
        )

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "服务器内部错误，请查看 logs/app.log",
                },
            },
        )

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return ok({"version": __version__, "data_dir": str(config.data_dir)})

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        settings = config.load_settings()
        prompt = config.resolve_prompt_path(settings)
        return ok(
            {
                "version": __version__,
                "data_dir": str(config.data_dir),
                "profiles_dir": str(config.profiles_dir),
                "prompt_path": str(prompt),
                "prompt_exists": prompt.exists(),
            }
        )

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        settings = config.load_settings()
        prompt = config.resolve_prompt_path(settings)
        python_prompt = config.resolve_prompt_path(settings, "python")
        mpatch = resolve_mpatch(settings)
        return ok(
            {
                "settings": settings,
                "prompt_path_resolved": str(prompt),
                "prompt_exists": prompt.exists(),
                "python_prompt_path_resolved": str(python_prompt),
                "python_prompt_exists": python_prompt.exists(),
                "mpatch": {
                    "available": mpatch is not None,
                    "path": str(mpatch) if mpatch else "",
                    "version": mpatch_version(mpatch) if mpatch else None,
                },
            }
        )

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        current = config.load_settings()
        update = {key: value for key, value in body.model_dump().items() if value is not None}
        current.update(update)
        saved = config.save_settings(current)
        return ok({"settings": saved})

    # --------------------------------------------------------------- projects
    @app.get("/api/projects")
    def get_projects() -> dict[str, Any]:
        return ok({"projects": list_profiles(config.profiles_dir)})

    @app.post("/api/projects")
    def post_project(body: ProjectBody) -> dict[str, Any]:
        profile = create_profile(config.profiles_dir, body.model_dump())
        return ok({"project": profile.to_dict()})

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        profile = load_profile(config.profiles_dir, project_id)
        return ok({"project": profile.to_dict()})

    @app.put("/api/projects/{project_id}")
    def put_project(project_id: str, body: ProjectBody) -> dict[str, Any]:
        profile = update_profile(config.profiles_dir, project_id, body.model_dump())
        return ok({"project": profile.to_dict()})

    @app.delete("/api/projects/{project_id}")
    def remove_project(project_id: str) -> dict[str, Any]:
        delete_profile(config.profiles_dir, project_id)
        delete_selection(config.selections_dir, project_id)
        return ok({"deleted": project_id})

    @app.get("/api/projects/{project_id}/tree")
    def get_tree(project_id: str, q: str | None = None) -> dict[str, Any]:
        profile = load_profile(config.profiles_dir, project_id)
        settings = config.load_settings()
        result = scan_project(profile, settings, data_dir=config.data_dir)
        data = result.as_dict()
        if q:
            ql = q.lower().replace("\\", "/")
            files = [item for item in data["files"] if ql in item["path"].lower()]
            data["files"] = files
            data["summary"]["filtered_count"] = len(files)
        return ok({"project": profile.to_dict(), **data})

    @app.get("/api/projects/{project_id}/selection")
    def get_selection(project_id: str) -> dict[str, Any]:
        load_profile(config.profiles_dir, project_id)
        return ok({"files": load_selection(config.selections_dir, project_id)})

    @app.put("/api/projects/{project_id}/selection")
    def put_selection(project_id: str, body: SelectionBody) -> dict[str, Any]:
        load_profile(config.profiles_dir, project_id)
        return ok({"files": save_selection(config.selections_dir, project_id, body.files)})

    @app.post("/api/projects/{project_id}/pack")
    def pack(project_id: str, body: PackBody) -> dict[str, Any]:
        profile = load_profile(config.profiles_dir, project_id)
        settings = config.load_settings()
        scan = scan_project(profile, settings, data_dir=config.data_dir)
        visible = {item.path for item in scan.files}
        requested = [path for path in body.files if path in visible]
        if len(requested) != len(set(body.files)):
            missing = sorted(set(body.files) - visible)
            raise AppError(
                "file_not_in_scope",
                "部分文件不在当前可选文件范围内，可能已被排除或修改",
                status=409,
                details={"files": missing[:100]},
            )
        mode = body.mode if body.mode in {"diff", "python"} else "diff"
        prompt_path = config.resolve_prompt_path(settings, mode)
        if not prompt_path.exists():
            raise AppError(
                "prompt_missing",
                f"提示词模板不存在：{prompt_path}",
                status=409,
                details={"path": str(prompt_path)},
            )
        prompt = read_text_file(prompt_path).text
        bundle = build_bundle(
            profile=profile,
            requirement=body.requirement,
            selected_paths=requested,
            prompt_template=prompt,
            mode=mode,
            max_bundle_bytes=int(settings.get("max_bundle_bytes") or 80 * 1024 * 1024),
        )
        session_id = store.create_session(
            project_id=profile.id,
            project_name=profile.name,
            root=profile.root,
            profile=profile.to_snapshot(),
            requirement=body.requirement,
            bundle_text=bundle.text,
            selection=bundle.selection,
            mode=mode,
            title=body.title,
        )
        directory = store.session_dir(session_id)
        return ok(
            {
                "session_id": session_id,
                "bundle_path": str(directory / "bundle.txt"),
                "bundle_bytes": len(bundle.text.encode("utf-8")),
                "bundle_size": len(bundle.text.encode("utf-8")),
                "file_count": bundle.file_count,
                "total_bytes": bundle.total_bytes,
                "token_estimate": bundle.token_estimate,
                "mode": bundle.mode,
                "selection": bundle.selection,
            }
        )

    # --------------------------------------------------------------- sessions
    @app.get("/api/sessions")
    def get_sessions(
        project_id: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        return ok(
            store.list_sessions(
                project_id=project_id,
                status=status,
                date_from=date_from,
                date_to=date_to,
                query=q,
                archived=archived,
            )
        )

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return ok(store.details(session_id))

    @app.get("/api/sessions/{session_id}/bundle")
    def get_bundle(session_id: str) -> PlainTextResponse:
        text = store.read_text(session_id, "bundle.txt")
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    @app.get("/api/sessions/{session_id}/answer")
    def get_answer(session_id: str) -> PlainTextResponse:
        text = store.read_text(session_id, "answer.md")
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    @app.post("/api/sessions/{session_id}/answer")
    def post_answer(session_id: str, body: AnswerBody) -> dict[str, Any]:
        parsed = store.save_answer(session_id, body.answer)
        details = store.details(session_id)
        return ok(
            {
                "parsed": parsed,
                "patches": details.get("patches") or [],
                "warnings": (parsed or {}).get("warnings") or [],
                "session": details,
            }
        )

    @app.post("/api/sessions/{session_id}/script/run")
    def run_script(session_id: str, body: ScriptRunBody | None = None) -> dict[str, Any]:
        body = body or ScriptRunBody()
        return ok(
            run_session_script(
                store,
                config,
                session_id,
                script_override=body.script,
                timeout_seconds=body.timeout_seconds,
            )
        )

    @app.put("/api/sessions/{session_id}/commit")
    def put_commit(session_id: str, body: CommitBody) -> dict[str, Any]:
        return ok({"parsed": store.update_commit(session_id, body.commit_message)})

    @app.put("/api/sessions/{session_id}/patches/{patch_id}")
    def put_patch(session_id: str, patch_id: str, body: PatchBody) -> dict[str, Any]:
        return ok({"patch": store.update_patch(session_id, patch_id, body.content)})

    @app.post("/api/sessions/{session_id}/patches/merge")
    def merge_patches(session_id: str, body: MergePatchesBody) -> dict[str, Any]:
        return ok(store.merge_patches(session_id, body.patch_ids))

    @app.post("/api/sessions/{session_id}/patches/{patch_id}/align-indent")
    def align_indent(
        session_id: str,
        patch_id: str,
        body: AlignIndentBody | None = None,
    ) -> dict[str, Any]:
        align_added = True if body is None else body.align_added
        return ok(
            align_session_patch(
                store,
                session_id,
                patch_id,
                align_added=align_added,
            )
        )

    @app.get("/api/sessions/{session_id}/patches/{patch_id}/mpatch")
    def get_mpatch(session_id: str, patch_id: str) -> dict[str, Any]:
        artifact = store.get_mpatch_artifact(session_id, patch_id)
        if artifact is None:
            raise AppError("mpatch_not_found", "还没有 mpatch 报告", status=404)
        return ok({"artifact": artifact})

    @app.post("/api/sessions/{session_id}/dry-run")
    def post_dry_run(session_id: str, body: DryRunBody) -> dict[str, Any]:
        return ok(dry_run(store, session_id, body.patch_ids, persist=body.persist))

    @app.post("/api/sessions/{session_id}/apply")
    def post_apply(session_id: str, body: ApplyBody) -> dict[str, Any]:
        result = apply_session(
            store,
            session_id,
            body.patch_ids,
            confirm_hash_changes=body.confirm_hash_changes,
        )
        return ok({"apply": result, "session": store.details(session_id)})

    @app.post("/api/sessions/{session_id}/revert")
    def post_revert(session_id: str, body: RevertBody) -> dict[str, Any]:
        result = revert_session(
            store,
            session_id,
            confirm_hash_changes=body.confirm_hash_changes,
        )
        return ok({"revert": result, "session": store.details(session_id)})

    @app.post("/api/sessions/{session_id}/reload")
    def post_reload(session_id: str) -> dict[str, Any]:
        new_id = store.reload(session_id)
        validation = None
        try:
            if store.get_patches(new_id):
                validation = dry_run(store, new_id, persist=False)
        except AppError:
            validation = None
        return ok(
            {
                "session_id": new_id,
                "session": store.details(new_id),
                "validation": validation,
            }
        )

    @app.post("/api/sessions/{session_id}/archive")
    def post_archive(session_id: str, body: ArchiveBody | None = None) -> dict[str, Any]:
        if store.has_unreverted_apply(session_id) and not (body and body.confirm_active_apply):
            raise AppError(
                "archive_active_apply",
                "该会话仍有未撤回的补丁应用。归档后如需撤回会先自动解压。确认归档吗？",
                status=409,
                details={"has_unreverted_apply": True},
            )
        return ok({"session": store.archive(session_id)})

    @app.delete("/api/sessions/{session_id}")
    def delete_session(
        session_id: str,
        confirm_active: bool = Query(False),
    ) -> dict[str, Any]:
        store.delete(session_id, confirm_active=confirm_active)
        return ok({"deleted": session_id})

    @app.post("/api/sessions/{session_id}/abandon")
    def abandon_session(session_id: str) -> dict[str, Any]:
        if store.has_any_apply(session_id):
            raise AppError(
                "apply_history",
                "已经应用过补丁的会话不能标记为放弃；如需继续请重新载入",
                status=409,
            )
        store.append_event(session_id, "abandon", {})
        return ok({"session": store._summary(session_id)})

    @app.get("/api/sessions/{session_id}/events")
    def get_events(session_id: str) -> dict[str, Any]:
        return ok({"events": store.events(session_id)})

    @app.get("/api/sessions/{session_id}/export")
    def export(session_id: str, format: str = Query("md")) -> Response:
        if format == "patch":
            content = combined_patch(store, session_id)
            filename = f"{session_id}-changes.patch"
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        if format == "md":
            content = export_markdown(store, session_id)
            filename = f"{session_id}.md"
            return Response(
                content=content,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        raise AppError("invalid_format", "导出格式必须是 md 或 patch")

    @app.get("/api/sessions/{session_id}/disk-diff")
    def get_disk_diff(session_id: str) -> dict[str, Any]:
        return ok(disk_diff(store, session_id))

    # --------------------------------------------------------- auto deepseek
    @app.post("/api/sessions/{session_id}/auto-deepseek")
    def post_auto_deepseek(session_id: str) -> dict[str, Any]:
        store.details(session_id)
        try:
            from .auto import send_to_deepseek  # type: ignore
        except ImportError as exc:
            raise AppError(
                "auto_unavailable",
                f"当前环境缺少自动化依赖：{exc}",
                status=503,
            ) from exc

        with auto_lock:
            if auto_state["running"]:
                raise AppError(
                    "auto_running",
                    "已有自动输入任务在运行，请等待完成",
                    status=409,
                    details={"session_id": auto_state.get("session_id")},
                )
            auto_state.update(
                {
                    "running": True,
                    "session_id": session_id,
                    "started_at": utc_now(),
                    "finished_at": None,
                    "success": None,
                    "message": "正在启动自动化…",
                }
            )

        try:
            directory = store.ensure_dir(session_id)
            bundle_path = str(directory / "bundle.txt")
            if not Path(bundle_path).is_file():
                raise AppError(
                    "bundle_missing",
                    "找不到打包文本文件，请重新生成打包",
                    status=409,
                )
            requirement = store.read_text(session_id, "requirement.md")
            if not requirement.strip():
                raise AppError(
                    "requirement_empty",
                    "该会话没有记录用户需求，无法自动输入",
                    status=409,
                )
        except Exception:
            with auto_lock:
                auto_state.update(
                    {
                        "running": False,
                        "finished_at": utc_now(),
                        "success": False,
                        "message": "读取会话打包信息失败",
                    }
                )
            raise

        def run() -> None:
            try:
                ok = send_to_deepseek(bundle_path, requirement)
                with auto_lock:
                    auto_state["success"] = bool(ok)
                    auto_state["message"] = (
                        "已完成自动输入，请人工确认后手动提交"
                        if ok
                        else "自动化失败，请检查 DeepSeek 页面是否已打开"
                    )
            except Exception as exc:
                logger.exception("auto-deepseek failed")
                with auto_lock:
                    auto_state["success"] = False
                    auto_state["message"] = f"自动化异常：{exc}"
            finally:
                with auto_lock:
                    auto_state["running"] = False
                    auto_state["finished_at"] = utc_now()

        threading.Thread(target=run, daemon=True, name="auto-deepseek").start()
        return ok({"started": True, "session_id": session_id})

    @app.get("/api/auto-deepseek/status")
    def get_auto_deepseek_status() -> dict[str, Any]:
        with auto_lock:
            return ok(dict(auto_state))

    # ------------------------------------------------------------------ index
    @app.get("/api/index/status")
    def index_status() -> dict[str, Any]:
        return ok(store.index_status())

    @app.post("/api/index/rebuild")
    def index_rebuild() -> dict[str, Any]:
        return ok({"sessions": store.rebuild_index(), "status": store.index_status()})

    return app
