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

## 其他覆盖

- 结构化错误：`tests/test_api.py::test_full_api_flow`
- 索引/事件：`tests/test_sessions.py::test_events_are_appended`
- 归档撤回自动解压：`tests/test_archive_revert.py::test_archived_session_can_be_reverted`
- 磁盘差异：`tests/test_archive_revert.py::test_disk_diff_reports_external_change`
- 大文件/二进制/.git 排除：`tests/test_profiles.py::test_scanner_skips_git_binary_large`
- 最终行无换行：`tests/test_diff_engine.py::test_modify_no_final_newline`、`tests/test_packing.py::test_content_is_not_reindented_and_final_newline`

## 手工冒烟

1. 双击 `start.bat`，浏览器打开工程列表。
2. 新建 profile，打开文件树，搜索/勾选目录。
3. 输入需求并打包，分别验证“复制完整文本”和“复制文件路径”。
4. 粘贴示例回答，查看 diff、warning、状态徽章。
5. 勾选部分文件应用，确认备份和事件。
6. 撤回，确认文件恢复。
7. 归档会话，刷新历史列表，打开详情并重新载入。
8. 在设置中修改大文件阈值/自动归档开关并刷新。
