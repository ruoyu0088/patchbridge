# Acceptance Matrix

> English companion to `docs/ACCEPTANCE_MATRIX.md`. Row numbers and test identifiers are unchanged.

| # | Acceptance criterion | Automated coverage |
|---|---|---|
| 1 | The profile's gitignore rules (including `!` negation) take effect correctly | `tests/test_profiles.py::test_profile_comments_and_negation`, `test_include_mode_whitelist`, file tree in `tests/test_api.py` |
| 2 | The bundle format is correct; content containing reserved markers is rejected and the conflicting files are listed | `tests/test_packing.py::test_bundle_contains_metadata_tree_and_content`, `test_marker_conflict_is_rejected`, `tests/test_api.py::test_pack_marker_conflict_returns_structured_error` |
| 3 | A well-formed answer yields the description, the commit suggestion, and each file's patch completely | `tests/test_parsing.py::test_normal_answer` |
| 4 | Malformed answers (missing headings / no language tag / `a/` prefixes) are still extracted, with warnings | `tests/test_parsing.py::test_malformed_answer_without_headings_or_language`, `test_missing_diff_header_uses_heading_path`, `test_absolute_path_and_prefixed_paths` |
| 5 | A file modified externally after packing shows a hash change and cannot be applied without confirmation | `tests/test_apply_revert.py::test_hash_change_requires_explicit_confirmation` |
| 6 | A context mismatch shows a conflict; after unticking that file the remaining files can still be applied | `tests/test_apply_revert.py::test_conflict_blocks_but_other_file_can_still_apply`, `tests/test_diff_engine.py::test_context_conflict` |
| 7 | Partial apply changes only the selected files; events are correct | `tests/test_apply_revert.py::test_partial_apply_and_backup`, `test_multiple_batches_and_lifo_revert` |
| 8 | Revert restores modified files and deletes newly created files | `tests/test_apply_revert.py::test_multiple_batches_and_lifo_revert`, `test_new_file_apply_and_revert_delete` |
| 9 | Revert requires confirmation when a file changed externally, then restores it from backup | `tests/test_apply_revert.py::test_revert_external_change_requires_confirmation` |
| 10 | After archiving the directory becomes a zip; it stays listed, its details remain readable, and it can be reloaded | `tests/test_sessions.py::test_archive_structure_and_reload`, `tests/test_archive_revert.py::test_export_from_archive` |
| 11 | A session directory deleted by hand is detected by the index, which can rebuild | `tests/test_sessions.py::test_index_detects_manual_directory_delete`, `tests/test_api.py::test_index_rebuild_endpoint` |
| 12 | Editing a patch after apply and applying again is rejected | `tests/test_apply_revert.py::test_patch_is_locked_after_apply` |
| 13 | The exported patch applies successfully on a clean copy | `tests/test_apply_revert.py::test_exported_patch_applies_in_clean_git_copy` |
| 14 | CRLF + BOM files keep their line endings and BOM after apply | `tests/test_apply_revert.py::test_crlf_bom_preserved_after_apply`, `tests/test_diff_engine.py::test_modify_preserves_crlf_and_bom` |
| 15 | Loading a malicious archive containing `../` is rejected | `tests/test_archive.py::test_safe_extract_rejects_unsafe_names`, `test_safe_extract_rejects_symlink_entry` |
| 16 | mpatch runs only on the copy; the real worktree is never written | `tests/test_mpatch.py::test_run_mpatch_never_writes_real_worktree` |
| 17 | After a strict failure the fuzzy fallback applies automatically and the final patch can be reviewed/applied/reverted | `tests/test_mpatch.py::test_fuzzy_fallback_applies_derived_patch` |
| 18 | An mpatch failure generates an AI repair request and applies nothing automatically | `tests/test_mpatch.py::test_fuzzy_failure_builds_repair_and_artifact`, `tests/test_api.py::test_mpatch_settings_and_artifact_endpoint` |
| 19 | Pure indentation conflicts are aligned automatically before mpatch runs | `tests/test_mpatch.py::test_uniform_indentation_is_fixed_before_mpatch`, `tests/test_diff_engine.py::test_align_indentation_accepts_already_aligned_top_level_line` |
| 20 | The mpatch-derived patch preserves the original file's BOM/CRLF | `tests/test_mpatch.py::test_mpatch_result_preserves_bom_and_crlf` |
| 21 | The automatic preview on the history page writes no mpatch artifacts | `tests/test_mpatch.py::test_preview_does_not_persist_mpatch_artifact` |
| 22 | Viewing an archived session does not unpack it just for the automatic preview | `tests/test_mpatch.py::test_preview_of_archived_session_does_not_unarchive` |
| 23 | The bundle header records Python mode, and the mode is stored with the session | `tests/test_scripting.py::test_python_bundle_header_and_mode`, `tests/test_api.py::test_python_mode_pack_and_script_api` |
| 24 | Python scripts run only in memory and generate appliable/revertable patches | `tests/test_scripting.py::test_script_runs_in_memory_and_generates_patch` |
| 25 | An `expected` mismatch applies the actual matches and records a warning | `tests/test_scripting.py::test_expected_mismatch_applies_actual_and_warns` |
| 26 | Out-of-scope paths are not modified and produce no patch; the result is marked partial | `tests/test_scripting.py::test_out_of_scope_path_is_partial_without_patch` |
| 27 | New files can be applied/reverted; a syntax error keeps the previous patches | `tests/test_scripting.py::test_create_file_patch_applies_and_reverts`, `test_invalid_script_keeps_existing_patches` |
| 28 | Patches generated by Python preserve the original file's BOM/CRLF | `tests/test_scripting.py::test_bom_and_crlf_survive_script_patch` |
| 29 | A Python code block without a language tag is still parsed | `tests/test_scripting.py::test_parse_script_without_language_fence` |
| 30 | The line-number/added/deleted structure of the side-by-side diff is correct | `tests/test_diff_view.py::test_side_by_side_rows_for_change`, `test_side_by_side_add_has_no_old_line`, `test_side_by_side_delete_has_no_new_line` |
| 31 | The exported document for a Python session includes the answer format and the script | `tests/test_scripting.py::test_export_markdown_contains_python_script` |
| 32 | Sequential API edits see the result of the previous step | `tests/test_scripting.py::test_sequential_edits_see_previous_changes` |
| 33 | Python patches preserve a missing final newline | `tests/test_scripting.py::test_no_final_newline_is_preserved` |
| 34 | Script steps and exceptions record the AI script line number | `tests/test_scripting.py::test_script_steps_and_runtime_errors_carry_source_lines`, `test_syntax_error_reports_line` |
| 35 | Commit/Python headings without `#` are still sectioned correctly | `tests/test_parsing.py::test_plain_headings_without_hash_are_recognized` |
| 36 | After switching 中文/English, the UI, backend diagnostics, and prompts stay consistent | `tests/test_i18n.py::test_english_errors_and_prompt_selection`, `test_english_profile_diagnostics`, `test_english_pack_uses_english_prompt` |
| 37 | English export labels do not fall back to Chinese | `tests/test_i18n.py::test_english_export_labels` |

## Other Coverage

- Structured errors: `tests/test_api.py::test_full_api_flow`
- Index/events: `tests/test_sessions.py::test_events_are_appended`
- Automatic unpacking on archive revert: `tests/test_archive_revert.py::test_archived_session_can_be_reverted`
- Disk diff: `tests/test_archive_revert.py::test_disk_diff_reports_external_change`
- Large file / binary / `.git` exclusion: `tests/test_profiles.py::test_scanner_skips_git_binary_large`
- No final newline: `tests/test_diff_engine.py::test_modify_no_final_newline`, `tests/test_packing.py::test_content_is_not_reindented_and_final_newline`
- Python syntax error boundary: `tests/test_scripting.py::test_invalid_script_keeps_existing_patches`
- Full Python-mode API flow: `tests/test_api.py::test_python_mode_pack_and_script_api`

## Manual Smoke Test

1. Double-click `start.bat`; the browser opens the project list. Switch to English at the bottom of the sidebar, confirm the UI, error messages, and the next bundle's prompt are English, then switch back to Chinese.
2. Create a profile, open the file tree, search, and tick a directory.
3. Enter a requirement and pack, verifying both "copy full text" and "copy file path".
4. Pack in Python mode and paste an answer containing `replace_text` + `assert_count`; confirm that it runs automatically and generates patches, that the "Python Script" tab shows line numbers and steps/OK, that clicking a step or an error line jumps to the corresponding script line, and that the review page shows a side-by-side diff.
5. Paste an answer whose `Commit 建议` and `Python 补丁脚本` headings have no leading `#`; confirm that the commit and the script are recognised separately.
6. Modify the script so that `expected` no longer matches; confirm that the actual matches are applied, a warning appears, and a patch is still generated.
7. Paste a diff answer into a Python session; confirm that it falls back to diff parsing and emits a warning.
8. Build a patch whose context has drifted slightly: after the dry-run it should show `mpatch 模糊` (mpatch fuzzy) with a correct derived diff. Then build a badly mismatched patch: it should show `mpatch 未命中` (mpatch missed) / `待 AI 修正` (awaiting AI repair) and allow the repair request to be copied.
9. Tick only some files and apply; confirm the backups and events.
10. Revert; confirm the files are restored.
11. Archive the session, refresh the history list, open the details, and reload.
12. Change the large-file threshold / automatic archive switch / Python prompt and timeout / mpatch path in Settings and refresh.
