"""Small request-scoped translation layer.

PatchBridge keeps Chinese as the source language for diagnostics.  This module
translates the final, user-facing text at the API boundary (and in a few
serializers) so the rest of the code can keep using stable Chinese messages.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

LANG_ZH = "zh"
LANG_EN = "en"
SUPPORTED_LANGUAGES = (LANG_ZH, LANG_EN)
DEFAULT_LANGUAGE = LANG_ZH

_LANGUAGE: ContextVar[str] = ContextVar("patchbridge_language", default=DEFAULT_LANGUAGE)


def normalize_language(value: str | None) -> str:
    if value and str(value).lower().startswith("en"):
        return LANG_EN
    return LANG_ZH


def language_from_header(value: str | None) -> str:
    """Pick a supported language from an Accept-Language style header."""
    if not value:
        return DEFAULT_LANGUAGE
    for part in value.split(","):
        token = part.split(";")[0].strip().lower()
        if token.startswith("en"):
            return LANG_EN
        if token.startswith("zh"):
            return LANG_ZH
    return DEFAULT_LANGUAGE


def get_language() -> str:
    return _LANGUAGE.get()


def set_language(value: str | None) -> Token[str]:
    return _LANGUAGE.set(normalize_language(value))


def reset_language(token: Token[str]) -> None:
    _LANGUAGE.reset(token)


@contextmanager
def language_scope(value: str | None) -> Iterator[None]:
    token = set_language(value)
    try:
        yield
    finally:
        reset_language(token)


# Chinese source -> English.  Keys are exact messages; dynamic messages use the
# patterns below.  Missing entries deliberately fall back to the source text.
MESSAGES_EN: dict[str, str] = {
    "请求参数不合法": "Invalid request parameters",
    "服务器内部错误，请查看 logs/app.log": "Internal server error; see logs/app.log",
    "部分文件不在当前可选文件范围内，可能已被排除或修改": "Some files are no longer in the selectable range; they may have been excluded or changed",
    "导出格式必须是 md 或 patch": "Export format must be md or patch",
    "已有自动输入任务在运行，请等待完成": "An automatic input task is already running; wait for it to finish",
    "正在启动自动化…": "Starting automation…",
    "找不到打包文本文件，请重新生成打包": "Bundle text file not found; generate the bundle again",
    "该会话没有记录用户需求，无法自动输入": "This session has no recorded requirement to enter automatically",
    "读取会话打包信息失败": "Could not read session bundle information",
    "已完成自动输入，请人工确认后手动提交": "Automatic input finished; review it and submit manually",
    "自动化失败，请检查 DeepSeek 页面是否已打开": "Automation failed; check that the DeepSeek page is open",
    "还没有 mpatch 报告": "No mpatch report yet",
    "会话 ID": "Session ID",
    "工程": "Project",
    "创建时间": "Created",
    "状态": "Status",
    "回答格式": "Answer format",
    "打包文件数": "Files in bundle",
    "打包字节数": "Bundle bytes",
    "需求": "Requirement",
    "选中文件": "Selected files",
    "修改说明": "Explanation",
    "AI 回答原文": "Original AI answer",
    "Python 补丁脚本": "Python patch script",
    "Commit 建议": "Commit suggestion",
    "警告": "Warnings",
    "文件补丁": "File patches",
    "操作事件": "Events",
    "新增 {added} 行，删除 {removed} 行": "Added {added} lines, removed {removed} lines",
    "，新增文件": " (new file)",
    "会话尚未应用补丁，没有“应用后”快照可比较": "This session has not applied patches, so there is no post-apply snapshot to compare",
    "缺少备份清单": "Backup manifest is missing",
    "备份已被清理，无法生成内容差异": "The backup was cleaned up, so content differences are unavailable",
    "没有差异": "No differences",
    "{count} 个文件与“应用后”不同": "{count} file(s) differ from the post-apply snapshot",
    "该会话仍有未撤回的补丁应用。归档后如需撤回会先自动解压。确认归档吗？": "This session still has an unreverted patch application. Archiving will auto-extract it when you revert. Archive anyway?",
    "已经应用过补丁的会话不能标记为放弃；如需继续请重新载入": "A session that has already applied patches cannot be abandoned; reload it to continue",
    "当前环境缺少自动化依赖：": "Automatic input dependencies are missing: ",
    "补丁无法解析": "Patch could not be parsed",
    "一个补丁条目只能包含一个文件": "A patch entry must contain exactly one file",
    "未尝试 mpatch": "mpatch was not attempted",
    "无法保存 mpatch 报告": "Could not save the mpatch report",
    "补丁缺少文件路径": "Patch has no file path",
    "目标路径不在 profile 允许的工程范围内": "Target path is outside the project range allowed by the profile",
    "补丁要新增文件，但目标已存在": "The patch creates a file, but the target already exists",
    "目标文件不存在": "Target file does not exist",
    "目标文件不在打包时选中的文件范围内": "Target file was not selected when the bundle was created",
    "严格匹配失败，自动对齐缩进后应用成功": "Strict matching failed; applying succeeded after automatic indentation alignment",
    "mpatch 未执行": "mpatch was not executed",
    "部分补丁不存在": "Some patches do not exist",
    "会话已应用补丁，不能再编辑补丁；请重新载入": "This session has applied patches; patches are locked. Reload it to edit again",
    "一个补丁条目只能包含一个文件，无法自动对齐": "A patch entry must contain exactly one file; automatic alignment is unavailable",
    "新增文件没有原文件可对齐：": "A new file has no source file to align: ",
    "目标文件不存在：": "Target file does not exist: ",
    "会话已应用过补丁，补丁内容已锁定；如需修改请重新载入生成新会话": "The session has applied patches and the patch content is locked; reload it as a new session to edit",
    "工程不是 git 仓库，拒绝应用补丁。请先在工程根目录执行 git init": "The project is not a git repository; patch application is refused. Run git init in the project root first",
    "会话没有可应用的补丁": "The session has no patches to apply",
    "请至少勾选一个补丁": "Select at least one patch",
    "选中的补丁已经应用过，不能再次应用；如需重做请重新载入": "The selected patches have already been applied. Reload to redo",
    "选中的补丁未通过应用前检查，已取消应用": "The selected patches did not pass pre-apply checks; application was cancelled",
    "以下文件在打包后发生了变化，必须显式确认后才能应用": "These files changed after bundling; explicit confirmation is required before applying",
    "多个补丁指向同一个文件": "Multiple patches point to the same file",
    "补丁没有计算结果": "The patch has no computed result",
    "无法读取会话根目录": "Could not read the session root",
    "回滚未能完整恢复所有文件，请检查备份": "Rollback did not fully restore every file; check the backup",
    "没有可撤回的补丁应用": "There is no patch application to revert",
    "apply 事件缺少 apply_id": "The apply event lacks apply_id",
    "apply 事件缺少备份清单": "The apply event lacks a backup manifest",
    "备份清单已被清理": "The backup manifest has been cleaned up",
    "以下文件在应用后又发生了变化，撤回会覆盖这些改动；请确认后重试": "These files changed after applying; reverting would overwrite those changes. Confirm and retry",
    "撤回过程中发生错误，备份仍然保留：": "An error occurred while reverting; the backup is still kept: ",
    "无法读取压缩包：": "Could not read archive: ",
    "压缩包条目是符号链接：": "Archive entry is a symlink: ",
    "压缩包内缺少：": "Archive is missing: ",
    "压缩包条目数量超过安全上限": "Archive has too many entries",
    "压缩包包含重复路径：": "Archive contains a duplicate path: ",
    "压缩包包含符号链接": "Archive contains symlinks",
    "压缩包解压后体积超过安全上限": "Archive expands beyond the safety limit",
    "压缩包条目越界：": "Archive entry escapes the target: ",
    "解压失败：": "Extraction failed: ",
    "会话没有补丁": "The session has no patches",
    "补丁无法导出：": "Patch could not be exported: ",
    "缺少备份清单": "Backup manifest is missing",
    "备份路径越界": "Backup path escapes the allowed root",
    "备份已被清理，无法生成内容差异": "The backup has been cleaned up; content diff is unavailable",
    "会话尚未应用补丁，没有“应用后”快照可比较": "The session has not applied patches; no post-apply snapshot is available",
    "没有差异": "No differences",
    "无法读取 JSON 文件：": "Could not read JSON file: ",
    "无法读取文件：": "Could not read file: ",
    "BOM 指示的编码无法解码：": "The encoding indicated by the BOM could not be decoded: ",
    "无法识别文本编码": "Could not detect text encoding",
    "无法识别文本编码：": "Could not detect text encoding: ",
    "修改后的内容无法用原文件编码保存": "The modified content cannot be saved in the original encoding",
    "补丁路径为空": "Patch path is empty",
    "补丁路径不是相对路径：": "Patch path is not relative: ",
    "补丁路径包含上级目录：": "Patch path contains a parent directory: ",
    "不允许修改 .git 目录：": "Modifying the .git directory is not allowed: ",
    "目标路径不在工程根目录内：": "Target path is outside the project root: ",
    "目标路径通过链接指向工程外：": "Target path points outside the project through a link: ",
    "压缩包包含空文件名": "Archive contains an empty filename",
    "压缩包路径包含反斜杠：": "Archive path contains a backslash: ",
    "压缩包包含绝对路径：": "Archive contains an absolute path: ",
    "压缩包路径包含上级目录：": "Archive path contains a parent directory: ",
    "未找到 mpatch": "mpatch was not found",
    "补丁上下文在当前文件中找不到": "Patch context was not found in the current file",
    "补丁可匹配多个位置，mpatch 拒绝猜测": "The patch matches multiple locations; mpatch refuses to guess",
    "无法在临时副本中初始化 git": "Could not initialize git in the temporary copy",
    "无法建立临时基线": "Could not create the temporary baseline",
    "无法收集 mpatch 结果": "Could not collect the mpatch result",
    "mpatch 执行成功，但副本没有产生 diff": "mpatch succeeded, but the copy produced no diff",
    "mpatch 模糊应用成功，已生成待复验的最终补丁": "mpatch fuzzy application succeeded; a final patch was generated for revalidation",
    "mpatch 副本流程失败：": "mpatch copy workflow failed: ",
    "mpatch 找不到补丁上下文": "mpatch could not find the patch context",
    "mpatch 找到多个可能位置，拒绝猜测": "mpatch found multiple possible locations and refused to guess",
    "mpatch 未能达到相似度阈值": "mpatch did not reach the similarity threshold",
    "mpatch 超时": "mpatch timed out",
    "mpatch 未能应用补丁": "mpatch could not apply the patch",
    "当前文件不是可解码文本，无法附上内容。": "The current file is not decodable text; its content cannot be attached.",
    "严格匹配失败": "Strict matching failed",
    "上下文不匹配": "Context mismatch",
    "不支持的打包模式": "Unsupported bundle mode",
    "需求不能为空": "Requirement cannot be empty",
    "请至少勾选一个文件": "Select at least one file",
    "单次打包文件数量过多，请收窄选择": "Too many files in one bundle; narrow the selection",
    "选中的文件不存在：": "Selected file does not exist: ",
    "文件不是受支持的文本：": "File is not supported text: ",
    "以下内容包含 PatchBridge 保留分隔符，拒绝打包": "The following content contains a reserved PatchBridge marker; bundling refused",
    "提示词模板包含 PatchBridge 保留分隔符": "The prompt template contains a reserved PatchBridge marker",
    "打包文本超过大小上限，请减少选中文件": "Bundle text exceeds the size limit; select fewer files",
    "AI 回答为空": "AI answer is empty",
    "补丁代码块缺少 diff 语言标记，已按 diff 解析": "Patch block has no diff language tag; parsed as diff",
    "补丁标题下的代码块不是有效的 unified diff": "The code block under the patch heading is not a valid unified diff",
    "补丁缺少文件头，已根据上方标题补全": "Patch has no file header; filled in from the heading above",
    "补丁解析失败：": "Patch parsing failed: ",
    "发现疑似补丁的代码块，但未能解析出文件": "A patch-like code block was found, but no file could be parsed",
    "文件路径来自补丁上方的标题": "File path came from the heading above the patch",
    "有补丁无法确定文件路径，请手工编辑": "Some patches have no file path; edit them manually",
    "补丁路径无效：": "Invalid patch path: ",
    "同一文件出现多个补丁：": "Multiple patches for the same file: ",
    "没有从回答中提取到任何文件补丁": "No file patches were extracted from the answer",
    "未找到修改说明": "No modification explanation found",
    "未找到 commit 建议": "No commit suggestion found",
    "未能提取 patch；请检查回答格式或手工粘贴补丁": "Could not extract patches; check the answer format or paste patches manually",
    "Python 代码块缺少 python 语言标记，已按脚本解析": "Python block has no python language tag; parsed as script",
    "发现多个 Python 代码块，已采用第一个": "Multiple Python blocks found; using the first",
    "Python 代码块缺少语言标记": "Python block has no language tag",
    "未找到 Python 代码块，已按整段回答作为脚本解析": "No Python code block found; the whole answer was parsed as a script",
    "没有从回答中提取到 Python 补丁脚本": "No Python patch script was extracted from the answer",
    "脚本中包含疑似 unified diff 的内容，请检查回答格式": "The script contains unified-diff-like content; check the answer format",
    "根目录不存在": "Project root does not exist",
    "根路径不是目录": "Project root is not a directory",
    "根目录不可访问：": "Project root is not accessible: ",
    "profile 缺少 root 配置": "Profile is missing the root setting",
    "mode 只能是 exclude 或 include": "mode must be exclude or include",
    "root 必须是绝对路径": "root must be an absolute path",
    "profile 没有规则，将按默认模式扫描全部文件": "Profile has no rules; the default mode will scan every file",
    "root 不能为空": "root cannot be empty",
    "profile ID 不合法": "Invalid profile ID",
    "工程不存在：": "Project does not exist: ",
    "工程 ID 已存在：": "Project ID already exists: ",
    "工程根目录不可访问": "Project root is not accessible",
    "脚本已超时，工作区已丢弃": "Script timed out; the workspace was discarded",
    "脚本执行超时": "Script execution timed out",
    "脚本执行超时，已丢弃本次运行的工作区": "Script execution timed out; this run's workspace was discarded",
    "会话已应用补丁，不能再执行脚本；请重新载入": "This session has applied patches; scripts cannot run. Reload it",
    "该会话不是 Python 模式": "This session is not in Python mode",
    "没有可执行的 Python 脚本": "There is no Python script to execute",
    "脚本执行完成，但没有文件发生变化": "Script finished, but no file changed",
    "会话不是 Python 模式": "Session is not in Python mode",
    "会话已应用补丁，不能再重新解析；请重新载入": "This session has applied patches; it cannot be reparsed. Reload it",
    "会话为 Python 模式，但回答中没有可执行的 Python API 程序；已按 diff 格式解析": "This is a Python-mode session, but the answer has no executable Python API program; parsed as a diff",
    "会话已应用补丁，commit 文本已锁定；请重新载入": "The session has applied patches; the commit text is locked. Reload it",
    "还没有解析 AI 回答": "The AI answer has not been parsed yet",
    "会话已应用补丁，补丁已锁定；请重新载入": "The session has applied patches; patches are locked. Reload it",
    "会话已应用补丁，不能再合并；请重新载入": "This session has applied patches; patches cannot be merged. Reload it",
    "至少需要两个不同的补丁才能合并": "At least two different patches are needed to merge",
    "只能合并指向同一文件的补丁": "Only patches that point to the same file can be merged",
    "会话仍有未撤回的补丁应用。删除会话不会还原磁盘文件。": "The session still has an unreverted patch application. Deleting it will not restore disk files.",
    "会话不存在：": "Session does not exist: ",
    "会话 ID 不合法": "Invalid session ID",
    "会话文件不存在：": "Session file does not exist: ",
    "会话文件不是合法 JSON：": "Session file is not valid JSON: ",
    "会话 meta.json 损坏": "Session meta.json is corrupted",
    "索引不存在": "Index does not exist",
    "索引与实际会话不一致": "Index does not match the sessions on disk",
    "索引正常": "Index is consistent",
    "不支持的会话模式": "Unsupported session mode",
    "未命名会话": "Untitled session",
    "补丁不存在：": "Patch does not exist: ",
    "补丁 ID 不合法": "Invalid patch ID",
    ".json 损坏": ".json is corrupted",
    "编辑后的补丁必须且只能包含一个文件": "An edited patch must contain exactly one file",
    "编辑后的补丁缺少文件路径": "The edited patch has no file path",
    "补丁无法解析为单文件补丁：": "Patch could not be parsed as a single-file patch: ",
    "目标文件不存在，无法验证合并结果：": "Target file does not exist; the merge result cannot be verified: ",
    "合并后的补丁无法应用：": "The merged patch cannot be applied: ",
    "不支持的补丁": "Unsupported patch",
    "新增文件没有原文件可对齐": "A new file has no source to align",
    "当前文件不是可编辑文本：": "The current file is not editable text: ",
    "没有找到可自动对齐的纯缩进差异；补丁可能已经对齐，或包含内容差异": "No pure indentation difference could be aligned; the patch may already be aligned or contain content changes",
    "对齐后仍无法应用：": "Still could not apply after alignment: ",
    "补丁上下文与当前文件不匹配": "Patch context does not match the current file",
    "没有可合并的补丁": "No patches to merge",
    "补丁不支持合并：": "Patch does not support merging: ",
    "不支持合并删除文件补丁": "Merging deleted-file patches is not supported",
    "不支持合并新增文件补丁": "Merging new-file patches is not supported",
    "补丁修改区域重叠：第 ": "Patch edit regions overlap: line ",
}

# Patterns for messages that include dynamic values.  They are applied only
# when no exact translation matched.
_PATTERN_SOURCES: list[tuple[str, str]] = [
    (r"^无法在 (.+) 上找到可用端口（从 (\d+) 开始）$", r"Could not find a free port on \1 (starting at \2)"),
    (r"^提示词模板不存在：(.+)$", r"Prompt template does not exist: \1"),
    (r"^当前环境缺少自动化依赖：(.+)$", r"Automatic input dependencies are missing: \1"),
    (r"^自动化异常：(.+)$", r"Automation error: \1"),
    (r"^自动化异常：(.+)$", r"Automation error: \1"),
    (r"^目标文件不存在：(.+)$", r"Target file does not exist: \1"),
    (r"^目标文件不是受支持的文本：(.+)$", r"Target file is not supported text: \1"),
    (r"^目标文件不在打包时选中的文件范围内：?(.*)$", r"Target file was not selected when the bundle was created: \1"),
    (r"^自动缩进对齐未执行：(.+)$", r"Automatic indentation alignment was not performed: \1"),
    (r"^；无法生成 mpatch 输入：(.+)$", r"; could not create mpatch input: \1"),
    (r"^mpatch 调用异常：(.+)$", r"mpatch invocation failed: \1"),
    (r"^mpatch 结果包含 (\d+) 个文件，期望 1 个$", r"mpatch result contains \1 files; expected 1"),
    (r"^mpatch 结果路径为 (.+)，期望 (.+)$", r"mpatch result path is \1; expected \2"),
    (r"^mpatch 结果未通过严格复验：(.+)$", r"mpatch result failed strict revalidation: \1"),
    (r"^mpatch dry-run 超时（(\d+) 秒）$", r"mpatch dry-run timed out (\1s)"),
    (r"^mpatch 应用超时（(\d+) 秒）$", r"mpatch application timed out (\1s)"),
    (r"^无法启动 mpatch：(.+)$", r"Could not start mpatch: \1"),
    (r"^mpatch 修改了非预期路径：(.+)$", r"mpatch changed an unexpected path: \1"),
    (r"^mpatch 执行成功，但副本没有产生 diff$", r"mpatch succeeded, but the copy produced no diff"),
    (r"^mpatch 副本流程失败：(.+)$", r"mpatch copy workflow failed: \1"),
    (r"^mpatch 未能达到相似度阈值：第 (\d+) 行，相似度 ([\d.]+)%，阈值 (\d+)%$", r"mpatch did not reach the similarity threshold: line \1, similarity \2%, threshold \3%"),
    (r"^会话已应用补丁，不能再编辑补丁；请重新载入$", r"The session has applied patches; patches are locked. Reload it"),
    (r"^补丁要新增文件，但目标在检查后出现：(.+)$", r"The patch creates a file, but the target appeared after the check: \1"),
    (r"^文件在 dry-run 后再次变化，请重新检查：(.+)$", r"File changed again after the dry-run; check again: \1"),
    (r"^写入后校验失败：(.+)$", r"Post-write verification failed: \1"),
    (r"^应用失败，已按备份回滚：(.+)$", r"Apply failed; rolled back from backup: \1"),
    (r"^无法读取压缩包：(.+)$", r"Could not read archive: \1"),
    (r"^压缩包条目是符号链接：(.+)$", r"Archive entry is a symlink: \1"),
    (r"^压缩包内缺少：(.+)$", r"Archive is missing: \1"),
    (r"^压缩包包含重复路径：(.+)$", r"Archive contains a duplicate path: \1"),
    (r"^压缩包条目越界：(.+)$", r"Archive entry escapes the target: \1"),
    (r"^解压失败：(.+)$", r"Extraction failed: \1"),
    (r"^补丁无法导出：(.+)$", r"Patch could not be exported: \1"),
    (r"^无法读取 JSON 文件：(.+)$", r"Could not read JSON file: \1"),
    (r"^无法读取文件：(.+)$", r"Could not read file: \1"),
    (r"^BOM 指示的编码无法解码：(.+)$", r"The encoding indicated by the BOM could not be decoded: \1"),
    (r"^无法识别文本编码：(.+)$", r"Could not detect text encoding: \1"),
    (r"^补丁路径不是相对路径：(.+)$", r"Patch path is not relative: \1"),
    (r"^补丁路径包含上级目录：(.+)$", r"Patch path contains a parent directory: \1"),
    (r"^不允许修改 \.git 目录：(.+)$", r"Modifying the .git directory is not allowed: \1"),
    (r"^目标路径不在工程根目录内：(.+)$", r"Target path is outside the project root: \1"),
    (r"^目标路径通过链接指向工程外：(.+)$", r"Target path points outside the project through a link: \1"),
    (r"^压缩包路径包含反斜杠：(.+)$", r"Archive path contains a backslash: \1"),
    (r"^压缩包包含绝对路径：(.+)$", r"Archive contains an absolute path: \1"),
    (r"^压缩包路径包含上级目录：(.+)$", r"Archive path contains a parent directory: \1"),
    (r"^未找到 mpatch$", r"mpatch was not found"),
    (r"^目标文件不存在：(.+)$", r"Target file does not exist: \1"),
    (r"^无法保存 mpatch 报告$", r"Could not save the mpatch report"),
    (r"^新建文件，(.+) 字符$", r"New file, \1 characters"),
    (r"^替换 (\d+) 处$", r"Replaced \1 occurrence(s)"),
    (r"^插入 (\d+) 处$", r"Inserted at \1 location(s)"),
    (r"^替换 1 个区间$", r"Replaced 1 range"),
    (r"^断言 count=(\d+)，实际 (\d+)$", r"Assert count=\1, actual \2"),
    (r"^包含目标文本$", r"Contains the target text"),
    (r"^未包含目标文本$", r"Does not contain the target text"),
    (r"^仍然包含目标文本$", r"Still contains the target text"),
    (r"^Python 语法错误：第 (\d+) 行：(.+)$", r"Python syntax error at line \1: \2"),
    (r"^脚本语法错误：第 (\d+) 行：(.+)$", r"Script syntax error at line \1: \2"),
    (r"^脚本执行完成，但没有文件发生变化$", r"Script finished, but no file changed"),
    (r"^文件未包含在本次会话中：(.+)$", r"File is not part of this session: \1"),
    (r"^文件不存在：(.+)$", r"File does not exist: \1"),
    (r"^文件已存在或已选中：(.+)$", r"File already exists or is selected: \1"),
    (r"^新文件不在 profile 可见范围内：(.+)$", r"New file is not visible under the profile: \1"),
    (r"^文件已存在于磁盘：(.+)$", r"File already exists on disk: \1"),
    (r"^不支持的正则 flag：(.+)$", r"Unsupported regular-expression flag: \1"),
    (r"^正则表达式无效：(.+)$", r"Invalid regular expression: \1"),
    (r"^不支持的打包模式$", r"Unsupported bundle mode"),
    (r"^需求不能为空$", r"Requirement cannot be empty"),
    (r"^请至少勾选一个文件$", r"Select at least one file"),
    (r"^单次打包文件数量过多，请收窄选择$", r"Too many files in one bundle; narrow the selection"),
    (r"^选中的文件不存在：(.+)$", r"Selected file does not exist: \1"),
    (r"^文件不是受支持的文本：(.+)$", r"File is not supported text: \1"),
    (r"^以下内容包含 PatchBridge 保留分隔符，拒绝打包$", r"The following content contains a reserved PatchBridge marker; bundling refused"),
    (r"^提示词模板包含 PatchBridge 保留分隔符$", r"The prompt template contains a reserved PatchBridge marker"),
    (r"^打包文本超过大小上限，请减少选中文件$", r"Bundle text exceeds the size limit; select fewer files"),
    (r"^未命名会话$", r"Untitled session"),
    (r"^会话不存在：(.+)$", r"Session does not exist: \1"),
    (r"^会话文件不存在：(.+)$", r"Session file does not exist: \1"),
    (r"^补丁不存在：(.+)$", r"Patch does not exist: \1"),
    (r"^补丁无法解析为单文件补丁：(.+)$", r"Patch could not be parsed as a single-file patch: \1"),
    (r"^目标文件不存在，无法验证合并结果：(.+)$", r"Target file does not exist; the merge result cannot be verified: \1"),
    (r"^合并后的补丁无法应用：(.+)$", r"The merged patch cannot be applied: \1"),
    (r"^补丁上下文与当前文件不匹配$", r"Patch context does not match the current file"),
    (r"^补丁不存在：(.+)$", r"Patch does not exist: \1"),
    (r"^补丁路径为空$", r"Patch path is empty"),
    (r"^补丁路径为 /dev/null$", r"Patch path is /dev/null"),
    (r"^补丁没有可解析的 hunk$", r"Patch has no parsable hunks"),
    (r"^补丁缺少文件路径$", r"Patch has no file path"),
    (r"^不支持的补丁$", r"Unsupported patch"),
    (r"^不支持重命名补丁$", r"Rename patches are not supported"),
    (r"^不支持复制文件补丁$", r"File-copy patches are not supported"),
    (r"^不支持二进制补丁$", r"Binary patches are not supported"),
    (r"^不支持删除文件补丁$", r"File-deletion patches are not supported"),
    (r"^不支持合并删除文件补丁$", r"Merging deleted-file patches is not supported"),
    (r"^不支持合并新增文件补丁$", r"Merging new-file patches is not supported"),
    (r"^没有可合并的补丁$", r"No patches to merge"),
    (r"^只能合并指向同一文件的补丁$", r"Only patches that point to the same file can be merged"),
    (r"^补丁不支持合并：(.+)$", r"Patch does not support merging: \1"),
    (r"^压缩包包含空文件名$", r"Archive contains an empty filename"),
    (r"^压缩包包含符号链接$", r"Archive contains symlinks"),
    (r"^压缩包条目数量超过安全上限$", r"Archive has too many entries"),
    (r"^压缩包解压后体积超过安全上限$", r"Archive expands beyond the safety limit"),
    (r"^索引不存在$", r"Index does not exist"),
    (r"^索引与实际会话不一致$", r"Index does not match the sessions on disk"),
    (r"^索引正常$", r"Index is consistent"),
    (r"^会话 meta.json 损坏$", r"Session meta.json is corrupted"),
    (r"^还没有解析 AI 回答$", r"The AI answer has not been parsed yet"),
    (r"^还没有 mpatch 报告$", r"No mpatch report yet"),
    (r"^还没有解析 AI 回答$", r"The AI answer has not been parsed yet"),
    (r"^该会话不是 Python 模式$", r"This session is not in Python mode"),
    (r"^没有可执行的 Python 脚本$", r"There is no Python script to execute"),
    (r"^该会话不是 Python 模式$", r"This session is not in Python mode"),
    (r"^脚本执行超时$", r"Script execution timed out"),
    (r"^脚本已超时，工作区已丢弃$", r"Script timed out; the workspace was discarded"),
    (r"^脚本执行超时，已丢弃本次运行的工作区$", r"Script execution timed out; this run's workspace was discarded"),
    (r"^print 只允许输出到捕获缓冲区$", r"print output may only go to the capture buffer"),
    (r"^(\w+) 不在允许列表中$", r"\1 is not in the allowlist"),
    (r"^expected 必须是非负整数$", r"expected must be a non-negative integer"),
    (r"^count 的 needle 不能为空$", r"count needle cannot be empty"),
    (r"^replace_text 的 old 不能为空$", r"replace_text old value cannot be empty"),
    (r"^replace_text 的 new 必须是字符串$", r"replace_text new value must be a string"),
    (r"^limit 必须是非负整数或 None$", r"limit must be a non-negative integer or None"),
    (r"^插入操作的 anchor 不能为空$", r"Insert anchor cannot be empty"),
    (r"^插入的 text 必须是字符串$", r"Inserted text must be a string"),
    (r"^replace_between 的 start/end 不能为空$", r"replace_between start/end cannot be empty"),
    (r"^replace_between 的 text 必须是字符串$", r"replace_between text must be a string"),
    (r"^create_file 的 text 必须是字符串$", r"create_file text must be a string"),
    (r"^锚点区间匹配 (\d+) 处，位置不唯一，已跳过修改$", r"Anchor range matched \1 locations; not unique, edit skipped"),
    (r"^mpatch 模糊应用成功；最终补丁由副本 git diff 生成，并已通过严格引擎复验$", r"mpatch fuzzy application succeeded; the final patch came from the copy's git diff and passed strict revalidation"),
    (r"^mpatch 结果未通过严格复验：(.+)$", r"mpatch result failed strict revalidation: \1"),
    (r"^严格匹配失败，自动对齐缩进后应用成功；(.+)$", r"Strict matching failed; the patch applied after indentation alignment; \1"),
    (r"^严格匹配失败，自动对齐缩进后应用成功$", r"Strict matching failed; the patch applied after indentation alignment"),
    (r"^严格匹配失败，自动对齐缩进后应用成功；无法生成 mpatch 输入：(.+)$", r"Strict matching failed; applying after indentation alignment succeeded, but the mpatch input could not be generated: \1"),
    (r"^补丁上下文第 (\d+) 行与当前文件第 (\d+) 行内容不同。$", r"Patch context line \1 differs from current file line \2."),
    (r"^补丁上下文第 (\d+) 行（当前文件第 (\d+) 行）的缩进不一致：补丁为 (\d+) 个前导空格，文件为 (\d+) 个；这一行在补丁中少了 (\d+) 个空格。$", r"Indentation differs at patch context line \1 (current file line \2): patch has \3 leading spaces, file has \4; this patch line is short by \5 spaces."),
    (r"^补丁上下文第 (\d+) 行（当前文件第 (\d+) 行）的缩进不一致：补丁为 (\d+) 个前导空格，文件为 (\d+) 个；这一行在补丁中多了 (\d+) 个空格。$", r"Indentation differs at patch context line \1 (current file line \2): patch has \3 leading spaces, file has \4; this patch line has \5 extra spaces."),
    (r"^补丁上下文在第 (\d+) 行之后超出了文件末尾。$", r"Patch context extends past the end of the file after line \1."),
    (r"^补丁上下文没有找到可对齐的位置。$", r"No alignable position was found for the patch context."),
    (r"^补丁期望从第 (\d+) 行开始，但当前文件只有 (\d+) 行。$", r"The patch expects to start at line \1, but the current file has only \2 lines."),
    (r"^根目录不存在$", r"Project root does not exist"),
    (r"^根路径不是目录$", r"Project root is not a directory"),
    (r"^根目录不可访问：(.+)$", r"Project root is not accessible: \1"),
    (r"^工程根目录不可访问$", r"Project root is not accessible"),
    (r"^第 (\d+) 行：未知小节 \[(.+)\]，已忽略$", r"Line \1: unknown section [\2]; ignored"),
    (r"^第 (\d+) 行：无法识别的配置行$", r"Line \1: unrecognized configuration line"),
    (r"^第 (\d+) 行：未知配置项 (.+)$", r"Line \1: unknown configuration key \2"),
    (r"^profile 没有规则，将按默认模式扫描全部文件$", r"The profile has no rules; all files will be scanned with the default mode"),
    (r"^文件数量超过上限 (\d+)，请收窄 profile 规则$", r"File count exceeds the limit (\1); narrow the profile rules"),
    (r"^工程不存在：(.+)$", r"Project does not exist: \1"),
    (r"^工程 ID 已存在：(.+)$", r"Project ID already exists: \1"),
    (r"^profile 缺少 root 配置$", r"The profile is missing the root setting"),
    (r"^mode 只能是 exclude 或 include$", r"mode must be exclude or include"),
    (r"^root 必须是绝对路径$", r"root must be an absolute path"),
    (r"^root 不能为空$", r"root cannot be empty"),
    (r"^profile ID 不合法$", r"Invalid profile ID"),
    (r"^不支持的会话模式$", r"Unsupported session mode"),
    (r"^编辑后的补丁必须且只能包含一个文件$", r"The edited patch must contain exactly one file"),
    (r"^编辑后的补丁缺少文件路径$", r"The edited patch has no file path"),
    (r"^至少需要两个不同的补丁才能合并$", r"At least two different patches are required to merge"),
    (r"^只能合并指向同一文件的补丁$", r"Only patches that point to the same file can be merged"),
    (r"^会话已应用补丁，不能再重新解析；请重新载入$", r"The session has applied patches and cannot be re-parsed; reload it"),
    (r"^会话已应用补丁，commit 文本已锁定；请重新载入$", r"The session has applied patches; the commit message is locked. Reload it"),
    (r"^会话已应用补丁，补丁已锁定；请重新载入$", r"The session has applied patches; patches are locked. Reload it"),
    (r"^会话已应用补丁，不能再合并；请重新载入$", r"The session has applied patches and cannot merge; reload it"),
    (r"^会话仍有未撤回的补丁应用。删除会话不会还原磁盘文件。$", r"This session still has an unreverted patch application. Deleting the session will not restore files on disk."),
    (r"^会话为 Python 模式，但回答中没有可执行的 Python API 程序；已按 diff 格式解析$", r"The session is in Python mode, but the answer has no executable Python API program; it was parsed as a diff instead"),
]

_PATTERNS_EN = [(re.compile(pattern), repl) for pattern, repl in _PATTERN_SOURCES]


def tr(text: str, **kwargs: Any) -> str:
    """Translate a user-facing message.  Unknown text falls back to Chinese."""
    if not text:
        return text
    value = text
    if get_language() == LANG_EN:
        value = MESSAGES_EN.get(text, text)
        if value == text:
            for pattern, repl in _PATTERNS_EN:
                if pattern.fullmatch(text):
                    value = pattern.sub(repl, text)
                    break
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return value
    return value


def localize_message(value: Any) -> Any:
    if isinstance(value, str):
        return tr(value)
    return value


def _localize_string_list(values: Any) -> Any:
    if not isinstance(values, list):
        return values
    return [tr(str(item)) if isinstance(item, str) else item for item in values]


def localize_profile_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Translate profile diagnostics returned by the API, not its rules/paths."""
    status = data.get("root_status")
    if isinstance(status, dict) and isinstance(status.get("error"), str):
        status["error"] = tr(status["error"])
    data["warnings"] = _localize_string_list(data.get("warnings"))
    return data


def localize_session_details(data: dict[str, Any]) -> dict[str, Any]:
    """Translate diagnostic strings stored in a session without touching user content."""
    parsed = data.get("parsed")
    if isinstance(parsed, dict):
        if isinstance(parsed.get("warnings"), list):
            parsed["warnings"] = _localize_string_list(parsed["warnings"])
        for patch in parsed.get("patches") or []:
            if isinstance(patch, dict):
                patch["warnings"] = _localize_string_list(patch.get("warnings"))
                patch["unsupported"] = tr(str(patch.get("unsupported"))) if patch.get("unsupported") else patch.get("unsupported")
    for patch in data.get("patches") or []:
        if isinstance(patch, dict):
            patch["warnings"] = _localize_string_list(patch.get("warnings"))
            patch["unsupported"] = tr(str(patch.get("unsupported"))) if patch.get("unsupported") else patch.get("unsupported")
    script = data.get("script")
    if isinstance(script, dict):
        report = script.get("report")
        if isinstance(report, dict):
            for key in ("reason", "error"):
                if isinstance(report.get(key), str):
                    report[key] = tr(report[key])
            report["warnings"] = _localize_string_list(report.get("warnings"))
            for step in report.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("message"), str):
                    step["message"] = tr(step["message"])
    for event in data.get("events") or []:
        if isinstance(event, dict) and isinstance(event.get("message"), str):
            event["message"] = tr(event["message"])
    for artifact in (data.get("mpatch") or {}).values():
        if not isinstance(artifact, dict):
            continue
        if isinstance(artifact.get("reason"), str):
            artifact["reason"] = tr(artifact["reason"])
        for key in ("diagnostics", "report"):
            report = artifact.get(key)
            if isinstance(report, dict) and isinstance(report.get("reason"), str):
                report["reason"] = tr(report["reason"])
    return data
