# 验收矩阵

| # | 验收标准 | 自动化覆盖 |
|---|---|---|
| 1 | profile 的 gitignore 规则（含 `!` 取反）正确生效 | `tests/test_profiles.py::test_profile_comments_and_negation`、`test_include_mode_whitelist`、`tests/test_api.py` 文件树 |
| 2 | 打包格式正确；内容含分隔符时拒绝并列出冲突文件 | `tests/test_packing.py::test_bundle_contains_metadata_tree_and_content`、`test_marker_conflict_is_rejected`、`tests/test_api.py::test_pack_marker_conflict_returns_structured_error` |
| 3 | 规范回答完整提取说明、commit、各文件补丁 | `tests/test_parsing.py::test_normal_answer` |
| 4 | 不规范回答（缺标题/无语言标记/`a/`）仍能提取并警告 | `tests/test_parsing.py::test_malformed_answer_without_headings_or_language`、`test_missing_diff_header_uses_heading_path`、`test_absolute_path_and_prefixed_paths` |
| 5 | 打包后文件被外部修改，显示 hash 变化，未确认不能应用 | `tests/test_apply_revert.py::test_hash_change_requires_explicit_confirmation` |
| 6 | 上下文不匹配显示冲突；取消勾选后其余文件可应用 | `tests/test_apply_revert.py::test_conflict_blocks_but_other_file_can_still_apply`、`tests/test_diff_engine.py::test_context_conflict` |
| 7 | 部分应用只改选中文件；事件正确 | `tests/test_apply_revert.py::test_partial_apply_and_backup`、`test_multiple_batches_and_lifo_revert` |
| 8 | 撤回还原修改文件、删除新增文件 | `tests/test_apply_revert.py::test_multiple_batches_and_lifo_revert`、`test_new_file_apply_and_revert_delete` |
| 9 | 撤回时文件被外部改过要确认，确认后按备份恢复 | `tests/test_apply_revert.py::test_revert_external_change_requires_confirmation` |
| 10 | 归档后目录变 zip，列表可见、详情可读、可重新载入 | `tests/test_sessions.py::test_archive_structure_and_reload`、`tests/test_archive_revert.py::test_export_from_archive` |
| 11 | 手动删除会话目录，索引发现不一致并支持重建 | `tests/test_sessions.py::test_index_detects_manual_directory_delete`、`tests/test_api.py::test_index_rebuild_endpoint` |
| 12 | 应用后修改补丁再应用被拒绝 | `tests/test_apply_revert.py::test_patch_is_locked_after_apply` |
| 13 | 导出补丁可在干净副本上成功应用 | `tests/test_apply_revert.py::test_exported_patch_applies_in_clean_git_copy` |
| 14 | CRLF + BOM 文件应用后换行/BOM 不变 | `tests/test_apply_revert.py::test_crlf_bom_preserved_after_apply`、`tests/test_diff_engine.py::test_modify_preserves_crlf_and_bom` |
| 15 | 含 `../` 的恶意压缩包加载被拒绝 | `tests/test_archive.py::test_safe_extract_rejects_unsafe_names`、`test_safe_extract_rejects_symlink_entry` |
| 16 | mpatch 只在副本运行，真实工作区不被写入 | `tests/test_mpatch.py::test_run_mpatch_never_writes_real_worktree` |
| 17 | 严格失败后自动模糊应用，最终补丁可审阅/应用/撤回 | `tests/test_mpatch.py::test_fuzzy_fallback_applies_derived_patch` |
| 18 | mpatch 失败生成 AI 修正请求，不自动应用 | `tests/test_mpatch.py::test_fuzzy_failure_builds_repair_and_artifact`、`tests/test_api.py::test_mpatch_settings_and_artifact_endpoint` |
| 19 | 纯缩进冲突在 mpatch 前自动对齐 | `tests/test_mpatch.py::test_uniform_indentation_is_fixed_before_mpatch`、`tests/test_diff_engine.py::test_align_indentation_accepts_already_aligned_top_level_line` |
| 20 | mpatch 派生补丁保持原文件 BOM/CRLF | `tests/test_mpatch.py::test_mpatch_result_preserves_bom_and_crlf` |
| 21 | 历史页自动预览不写 mpatch 工件 | `tests/test_mpatch.py::test_preview_does_not_persist_mpatch_artifact` |
| 22 | 查看归档会话不因自动预览而解压 | `tests/test_mpatch.py::test_preview_of_archived_session_does_not_unarchive` |
| 23 | 打包头记录 Python 模式，模式随会话保存 | `tests/test_scripting.py::test_python_bundle_header_and_mode`、`tests/test_api.py::test_python_mode_pack_and_script_api` |
| 24 | Python 脚本只在内存执行并生成可应用/撤回补丁 | `tests/test_scripting.py::test_script_runs_in_memory_and_generates_patch` |
| 25 | `expected` 不符时按实际匹配应用并 warning | `tests/test_scripting.py::test_expected_mismatch_applies_actual_and_warns` |
| 26 | 越界路径不修改、不生成补丁，结果标记 partial | `tests/test_scripting.py::test_out_of_scope_path_is_partial_without_patch` |
| 27 | 新建文件可应用/撤回；语法错误保留旧补丁 | `tests/test_scripting.py::test_create_file_patch_applies_and_reverts`、`test_invalid_script_keeps_existing_patches` |
| 28 | Python 生成补丁保持原文件 BOM/CRLF | `tests/test_scripting.py::test_bom_and_crlf_survive_script_patch` |
| 29 | 无语言标记的 Python 代码块仍可解析 | `tests/test_scripting.py::test_parse_script_without_language_fence` |
| 30 | 并排 diff 的行号/新增/删除结构正确 | `tests/test_diff_view.py::test_side_by_side_rows_for_change`、`test_side_by_side_add_has_no_old_line`、`test_side_by_side_delete_has_no_new_line` |
| 31 | Python 会话导出文档包含回答格式与脚本 | `tests/test_scripting.py::test_export_markdown_contains_python_script` |
| 32 | 顺序 API 修改能看到前一步结果 | `tests/test_scripting.py::test_sequential_edits_see_previous_changes` |
| 33 | Python 补丁保持原文件“无末尾换行” | `tests/test_scripting.py::test_no_final_newline_is_preserved` |
| 34 | 脚本步骤/异常记录 AI 脚本行号 | `tests/test_scripting.py::test_script_steps_and_runtime_errors_carry_source_lines`、`test_syntax_error_reports_line` |
| 35 | 无 `#` 的 Commit/Python 标题仍能正确分节 | `tests/test_parsing.py::test_plain_headings_without_hash_are_recognized` |

## 其他覆盖

- 结构化错误：`tests/test_api.py::test_full_api_flow`
- 索引/事件：`tests/test_sessions.py::test_events_are_appended`
- 归档撤回自动解压：`tests/test_archive_revert.py::test_archived_session_can_be_reverted`
- 磁盘差异：`tests/test_archive_revert.py::test_disk_diff_reports_external_change`
- 大文件/二进制/.git 排除：`tests/test_profiles.py::test_scanner_skips_git_binary_large`
- 最终行无换行：`tests/test_diff_engine.py::test_modify_no_final_newline`、`tests/test_packing.py::test_content_is_not_reindented_and_final_newline`
- Python 语法错误边界：`tests/test_scripting.py::test_invalid_script_keeps_existing_patches`
- Python 模式 API 全流程：`tests/test_api.py::test_python_mode_pack_and_script_api`

## 手工冒烟

1. 双击 `start.bat`，浏览器打开工程列表。
2. 新建 profile，打开文件树，搜索/勾选目录。
3. 输入需求并打包，分别验证“复制完整文本”和“复制文件路径”。
4. 以 Python 模式打包，粘贴含 `replace_text` + `assert_count` 的回答；确认自动执行、生成补丁，
   “Python 脚本”页显示行号、步骤/OK，点击步骤或错误行号能跳到脚本对应行；审阅页显示左右并排 diff。
5. 粘贴一份 `Commit 建议`、`Python 补丁脚本` 前不带 `#` 的回答，确认 commit 与脚本分别识别。
6. 修改脚本使 `expected` 不符，确认按实际匹配应用、出现 warning、仍能生成补丁。
7. 粘贴 diff 回答（Python 会话），确认回退为 diff 解析并给出 warning。
8. 构造上下文轻微漂移的补丁：dry-run 后应显示 `mpatch 模糊`，derived diff 正确；再构造
   严重不匹配的补丁：应显示 `mpatch 未命中`/`待 AI 修正`，能复制修正请求。
9. 勾选部分文件应用，确认备份和事件。
10. 撤回，确认文件恢复。
11. 归档会话，刷新历史列表，打开详情并重新载入。
12. 在设置中修改大文件阈值/自动归档开关/Python 提示词与超时/mpatch 路径并刷新。
