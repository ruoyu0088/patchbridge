// PatchBridge 前端 i18n。
//
// 中文是默认语言，也是“源语言”：t() 的 key 就是界面上的中文原文。
// 英文词典按中文 key 覆盖；找不到 key 时回退到中文原文，因此漏翻只会
// 退化成中文，不会出现空白或报错。
//
// 语言切换通过整页 reload 完成（reloadWithLocale），这样：
// - 所有已渲染的文案（包括 computed / 字典常量）都会按新语言重新求值；
// - 后端重新协商 Accept-Language，诊断文本和提示词模板跟随切换；
// - location.hash 保持不变，当前页面/会话不丢。

export const LOCALE_KEY = 'patchbridge.locale';
export const DEFAULT_LOCALE = 'zh';
export const SUPPORTED_LOCALES = ['zh', 'en'];

const SUPPORTED = new Set(SUPPORTED_LOCALES);

const TITLES = {
  zh: 'PatchBridge',
  en: 'PatchBridge — safe patches from Web AI',
};

// 中文原文 -> English。只放界面文案；用户内容（路径、diff、会话标题、
// commit 文本、脚本源码、后端返回的错误/详情）一律不翻译。
export const DICT = {
  // ── 通用 ───────────────────────────────────────────────────────────
  '加载中…': 'Loading…',
  '读取中…': 'Loading…',
  '保存中…': 'Saving…',
  '取消': 'Cancel',
  '保存': 'Save',
  '关闭': 'Close',
  '确认': 'OK',
  '请确认': 'Please confirm',
  '删除': 'Delete',
  '编辑': 'Edit',
  '复制': 'Copy',
  '刷新': 'Refresh',
  '下载': 'Download',
  '检查': 'Check',
  '打开': 'Open',
  '可用': 'Available',
  '不可用': 'Unavailable',
  '存在': 'Found',
  '不存在': 'Not found',
  '未找到': 'Not found',
  '未知': 'Unknown',
  '内容': 'Content',
  '{label}已复制到剪贴板': '{label} copied to clipboard',
  '复制失败，请手工选择文本': 'Copy failed; select the text manually',
  '无法连接 PatchBridge 后端': 'Cannot reach the PatchBridge backend',
  '请求失败': 'Request failed',
  '界面语言': 'Interface language',
  '切换到中文界面': 'Switch to Chinese',
  '切换到英文界面': 'Switch to English',
  '没有可显示的 diff': 'No diff to display',
  '没有可显示的差异': 'No differences to display',
  '有步骤失败': 'Some steps failed',

  // ── 会话状态 / 补丁状态 ───────────────────────────────────────────
  '待 AI 回答': 'Waiting for AI',
  '已解析': 'Parsed',
  '已应用': 'Applied',
  '已撤回': 'Reverted',
  '已放弃': 'Abandoned',
  '数据损坏': 'Corrupted',
  'hash 一致': 'Hash matches',
  'hash 变化': 'Hash changed',
  '文件缺失': 'File missing',
  '新增文件': 'New file',
  '未选中': 'Not selected',
  '可应用': 'Appliable',
  '冲突': 'Conflict',
  '不支持': 'Unsupported',
  '未检查': 'Not checked',
  '范围内': 'In scope',
  '工程外': 'Outside project',
  '被 profile 排除': 'Excluded by profile',

  // ── 侧边栏 / 外壳 ─────────────────────────────────────────────────
  '工程': 'Projects',
  '历史': 'History',
  '历史会话': 'History',
  '设置': 'Settings',
  'Web AI → 安全补丁': 'Web AI → safe patches',
  '打开工程列表页面': 'Open the projects page',
  '打开历史会话页面': 'Open the history page',
  '暂无工程': 'No projects yet',
  '暂无会话': 'No sessions yet',
  '手工复制，不调用模型 API': 'Copy by hand; no model API calls',
  '页面不存在。': 'Page not found.',
  '返回工程': 'Back to projects',
  '正在自动输入 DeepSeek，请不要操作键盘和鼠标…':
    'Auto-filling DeepSeek; do not touch the keyboard or mouse…',
  'DeepSeek 自动输入完成，请人工确认后手动提交':
    'DeepSeek auto-input finished; review and submit manually',
  '自动输入失败：{error}': 'Auto-input failed: {error}',

  // ── 工程列表 ──────────────────────────────────────────────────────
  '每个工程由一个 profile 文件定义根目录和 gitignore 规则。':
    'Each project is defined by a profile file that sets the root folder and gitignore rules.',
  '新建工程': 'New project',
  '还没有工程。点击“新建工程”创建第一个 profile。':
    'No projects yet. Click “New project” to create your first profile.',
  '（未设置根目录）': '(no root folder set)',
  '模式：{mode}': 'Mode: {mode}',
  '包含白名单': 'Allowlist',
  '排除': 'Exclude',
  '规则：{count}': 'Rules: {count}',
  '，禁止打包。': ', packing is disabled.',
  '编辑 profile': 'Edit profile',
  '新建 profile': 'New profile',
  '纯文本 profile：root 必须是绝对路径；mode 为 exclude 或 include； [rules] 使用 gitignore 语法，支持 ! 取反。':
    'Plain-text profile: root must be an absolute path; mode is exclude or include; [rules] uses gitignore syntax and supports ! negation.',
  '删除工程': 'Delete project',
  '确定删除工程「{name}」的 profile 吗？历史会话会保留。':
    'Delete the profile of project “{name}”? Session history is kept.',
  'profile 已保存': 'Profile saved',
  '工程已删除': 'Project deleted',
  '新工程': 'New project',

  // ── 工程详情 / 打包 ───────────────────────────────────────────────
  '← 工程列表': '← Projects',
  '{count} 个可选文件': '{count} selectable files',
  '大文件 {count}': 'Large files {count}',
  '二进制 {count}': 'Binary {count}',
  '加载文件树…': 'Loading file tree…',
  '根目录不可访问，禁止打包。请编辑 profile 修正 root。':
    'The root folder is not accessible, so packing is disabled. Edit the profile to fix root.',
  '根目录不可访问': 'Root folder is not accessible',
  '文件树': 'File tree',
  '编辑工程定义': 'Edit project profile',
  '全选当前': 'Select all shown',
  '清空': 'Clear',
  '按路径搜索…': 'Search by path…',
  '没有匹配的文件': 'No matching files',
  '已选': 'Selected',
  '个文件，共 {size}': 'files, {size} total',
  '纯文本 profile：root 必须是绝对路径；mode 为 exclude 或 include； [rules] 使用 gitignore 语法，支持 ! 取反。保存后文件树会立即刷新。':
    'Plain-text profile: root must be an absolute path; mode is exclude or include; [rules] uses gitignore syntax and supports ! negation. The file tree refreshes right after saving.',
  '保存并刷新文件树': 'Save and refresh tree',
  '需求与打包': 'Requirement and packing',
  '回答格式': 'Answer format',
  'AI 调用补丁 API，不写 diff、不算行号；推荐':
    'The AI calls the patch API; no diffs or line numbers; recommended',
  '传统格式，兼容旧会话和外部工具':
    'Classic format, compatible with old sessions and external tools',
  '修改需求': 'Requirement',
  '说明要改什么、期望的行为、限制和验收标准…':
    'Describe what to change, expected behaviour, constraints and acceptance criteria…',
  '打包中…': 'Packing…',
  '生成打包文本': 'Generate bundle text',
  '打包前会记录每个文件的 sha256 快照。':
    'A sha256 snapshot of every file is recorded before packing.',
  '打包完成': 'Packing complete',
  '打包完成。现在可以把完整文本或文件路径交给 Web AI。':
    'Packing complete. You can now hand the full text or the file path to the Web AI.',
  '{count} 个文件': '{count} files',
  'Python 脚本模式': 'Python script mode',
  'diff 模式': 'diff mode',
  '约 {count} tokens': '~{count} tokens',
  '两种方式任选其一交给 Web AI：复制完整文本，或复制下面的文件路径后在本地打开/上传文件。':
    'Hand it to the Web AI either way: copy the full text, or copy the file path below and open/upload the file locally.',
  '复制文件路径': 'Copy file path',
  '复制完整文本': 'Copy full text',
  '下载文本文件': 'Download text file',
  '收起预览': 'Hide preview',
  '预览文本': 'Preview text',
  '打开审阅页 →': 'Open review page →',
  '启动中…': 'Starting…',
  '自动输入到 DeepSeek': 'Auto-fill into DeepSeek',
  '将自动粘贴需求并把 bundle.txt 作为附件上传，不会自动提交；完成后请人工确认后手动发送。':
    'Pastes the requirement and uploads bundle.txt as an attachment; it never submits. Review and send manually when done.',
  '打包文本保存于会话': 'The bundle text is saved in session',
  '，之后可在历史中重新载入。': '; you can reload it from history later.',
  '保存文件选择失败：{error}': 'Failed to save file selection: {error}',
  '请先输入需求': 'Enter a requirement first',
  '请至少勾选一个文件': 'Select at least one file',
  '已有自动输入任务在运行': 'An auto-input task is already running',
  '正在启动自动化…': 'Starting automation…',
  '已启动自动输入，请不要操作键盘和鼠标':
    'Auto-input started; do not touch the keyboard or mouse',
  '工程定义已保存，文件树已刷新': 'Project profile saved; file tree refreshed',
  '文件绝对路径': 'Absolute file path',
  '打包全文': 'Bundle text',
  '打包文件路径': 'Bundle file path',
  'Python 脚本': 'Python script',
  '已自动排除的二进制文件': 'Automatically excluded binary files',
  '点击路径可复制绝对路径；这些文件不会出现在文件树中。':
    'Click a path to copy its absolute form; these files never appear in the file tree.',
  '如果其中某个文件其实是文本，请检查文件编码或内容；PatchBridge 只把无法可靠识别为文本的文件归为二进制。':
    'If one of these is really text, check its encoding or content; PatchBridge only treats files it cannot reliably read as text as binary.',
  '复制绝对路径': 'Copy absolute path',
  '二进制文件超过显示上限，这里只列出前 {shown} 个，共 {total} 个。':
    'More binary files than the display limit: showing the first {shown} of {total}.',

  // ── 会话审阅：通用 ────────────────────────────────────────────────
  '加载会话…': 'Loading session…',
  '← 返回': '← Back',
  '会话审阅': 'Session review',
  '重新载入': 'Reload',
  '归档': 'Archive',
  '导出文档': 'Export doc',
  '导出 patch': 'Export patch',
  '已归档': 'Archived',
  '该会话已归档。详情可直接读取；应用、撤回、重新载入等操作会自动解压。':
    'This session is archived. Details open directly; apply, revert and reload unpack it automatically.',
  '补丁审阅': 'Patch review',
  '打包文本': 'Bundle text',
  'AI 回答': 'AI answer',
  '事件': 'Events',
  '磁盘差异': 'Disk diff',

  // ── 会话审阅：回答 / commit ───────────────────────────────────────
  '用户 Prompt': 'User prompt',
  '复制 Prompt': 'Copy prompt',
  '（该会话没有记录用户 Prompt）': '(no user prompt recorded for this session)',
  '粘贴 AI 的完整回答': 'Paste the full AI answer',
  '把 Web AI 输出的所有内容原样粘贴到这里。PatchBridge 会自动寻找修改说明、commit 建议和 unified diff。':
    'Paste everything the Web AI returned, verbatim. PatchBridge finds the explanation, commit suggestion and unified diff.',
  '粘贴 AI 回答全文…': 'Paste the full AI answer…',
  '解析中…': 'Parsing…',
  '解析回答并提取补丁': 'Parse answer and extract patches',
  '修改说明': 'Explanation',
  '（未提取到修改说明）': '(no explanation extracted)',
  'Commit 建议': 'Commit suggestion',
  '（未提取到 commit 建议）': '(no commit suggestion extracted)',
  '解析警告': 'Parse warnings',
  '已应用 {count} 个文件：{paths}': 'Applied {count} file(s): {paths}',

  // ── 会话审阅：补丁工具栏 / 徽标 ───────────────────────────────────
  '反选未应用': 'Invert unapplied',
  '已选 {selected} / {total}': '{selected} / {total} selected',
  '上下文': 'Context',
  '合并中…': 'Merging…',
  '合并同文件 diff（{count} 组）': 'Merge diffs per file ({count} group(s))',
  '全部 dry-run': 'Dry-run all',
  '应用选中补丁': 'Apply selected patches',
  '撤回中…': 'Reverting…',
  '撤回最近一次应用': 'Revert last apply',
  '本会话已经应用过补丁，补丁与 commit 文本已锁定。未应用的文件仍可应用；如需修改补丁，请使用“重新载入”生成新会话。':
    'Patches have been applied in this session, so patches and the commit message are locked. Unapplied files can still be applied; to edit patches, use “Reload” to create a new session.',
  '新增': 'New',
  'mpatch 模糊': 'mpatch fuzzy',
  'mpatch 未命中': 'mpatch missed',
  '自动对齐': 'Auto-aligned',
  '待 AI 修正': 'Needs AI fix',
  '本批次已应用': 'Applied in this batch',
  '对齐中…': 'Aligning…',
  '一键对齐缩进': 'Auto-align indentation',
  '打开补丁编辑器': 'Open patch editor',

  // ── 会话审阅：冲突 / 修正 ────────────────────────────────────────
  '严格匹配和 mpatch 都没能应用这个补丁。':
    'Neither strict matching nor mpatch could apply this patch.',
  '已按 mpatch 的失败位置生成修正请求，复制给 Web AI 重新生成即可。':
    'A fix request was generated from the mpatch failure point; copy it to the Web AI to regenerate.',
  '复制 AI 修正请求': 'Copy AI fix request',
  '仍要手工编辑': 'Edit manually anyway',
  '查看修正请求内容': 'Show fix request',
  '当前补丁没有 AI 修正请求': 'This patch has no AI fix request',
  'AI 修正请求': 'AI fix request',

  // ── 会话审阅：补丁编辑器 ─────────────────────────────────────────
  '补丁编辑器': 'Patch editor',
  '保存后会重新解析并 dry-run': 'Saving re-parses and dry-runs the patch',
  '同时平移新增行': 'Shift added lines too',
  '撤销对齐': 'Undo align',
  '恢复当前补丁': 'Reset to current patch',
  '保存并重新检查': 'Save and re-check',
  '已填入对齐后的补丁，但尚未保存。下面是保存前的冲突参考，便于核对。':
    'The aligned patch is filled in but not saved yet. The pre-save conflict reference below helps you verify it.',
  '冲突定位：': 'Conflict at: ',
  '补丁缩进 {patch} 个空格 / 文件缩进 {file} 个空格':
    'Patch indent {patch} spaces / file indent {file} spaces',
  '补丁上下文': 'Patch context',
  '当前文件': 'Current file',
  'mpatch 已在临时副本中完成模糊应用，下面显示的是由副本 git diff 生成的最终补丁；应用时会再次用严格引擎校验。':
    'mpatch applied fuzzily in a temporary copy; the final patch below comes from a git diff of that copy. It is re-checked with the strict engine when applied.',
  '查看原始补丁': 'Show raw patch',
  '单文件 dry-run': 'Dry-run this file',
  '编辑补丁': 'Edit patch',
  'hunk {hunk}: {sign}{count} {unit}': 'hunk {hunk}: {sign}{count} {unit}',
  '空格': 'spaces',
  '已对齐缩进（{summary}），请检查后保存':
    'Indentation aligned ({summary}); review before saving',
  '已对齐缩进，请检查后保存': 'Indentation aligned; review before saving',
  '无法自动对齐缩进': 'Could not align indentation automatically',
  '已撤销对齐，补丁文本已恢复': 'Align undone; patch text restored',
  '补丁已更新，正在重新检查': 'Patch updated; re-checking',

  // ── 会话审阅：侧栏 ───────────────────────────────────────────────
  '会话信息': 'Session info',
  '根目录': 'Root folder',
  '创建': 'Created',
  '文件数': 'Files',
  '大小': 'Size',
  '交给 AI 的文本': 'Text for the AI',
  '可以复制全文，或复制文件完整路径。':
    'Copy the full text, or copy the bundle file path.',
  '（已归档）': '(archived)',
  '复制全文': 'Copy all text',
  '快捷操作': 'Quick actions',
  '替换 AI 回答': 'Replace AI answer',
  '查看事件': 'View events',
  '比较磁盘': 'Compare disk',
  '标记为已放弃': 'Mark as abandoned',

  // ── 会话审阅：打包文本 tab ───────────────────────────────────────
  '（已归档，压缩包：{path}）': '(archived, zip: {path})',
  '加载 / 复制完整文本': 'Load / copy full text',
  '归档会话没有可直接复制的未压缩文件路径，请先重新载入':
    'Archived sessions have no uncompressed bundle path; reload the session first',

  // ── 会话审阅：AI 回答 tab ────────────────────────────────────────
  'AI 回答原文': 'Raw AI answer',
  '重新粘贴一份完整回答会覆盖当前解析结果。已应用的会话不能重新解析。':
    'Pasting a full answer again replaces the current parse. Sessions with applied patches cannot be re-parsed.',
  '粘贴新的 AI 回答全文…': 'Paste a new full AI answer…',
  '重新解析': 'Parse again',
  '（还没有保存 AI 回答）': '(no AI answer saved yet)',
  '请先粘贴 AI 回答': 'Paste the AI answer first',
  '解析完成，提取到 {count} 个文件补丁':
    'Parsed; {count} file patch(es) extracted',

  // ── 会话审阅：Python 脚本 tab ────────────────────────────────────
  'Python 补丁脚本': 'Python patch script',
  '复制脚本': 'Copy script',
  '执行中…': 'Running…',
  '执行脚本': 'Run script',
  '脚本只会修改内存中的工作区；执行成功或部分成功后才会生成补丁。真实文件在“应用选中补丁”之前不会改变。':
    'The script only changes an in-memory workspace and produces patches on success or partial success. Real files stay untouched until you click “Apply selected patches”.',
  'AI 输出的 Python 补丁脚本…': 'Python patch script from the AI…',
  '会话已应用补丁，脚本已锁定；如需再改请“重新载入”。':
    'Patches were applied, so the script is locked. Use “Reload” to change it.',
  '第 {line} 行': 'Line {line}',
  '执行步骤（{count}）': 'Steps ({count})',
  '没有可执行的 Python 脚本': 'No Python script to run',
  'Python 脚本执行完成，生成 {count} 个文件补丁':
    'Python script finished; {count} file patch(es) generated',
  '脚本部分执行：{error}；已生成 {count} 个补丁':
    'Script partially ran: {error}; {count} patch(es) generated',
  '脚本未执行：{reason}': 'Script did not run: {reason}',
  '已提取 Python 脚本，正在内存工作区执行…':
    'Python script extracted; running it in the in-memory workspace…',

  // ── 会话审阅：事件 / 磁盘 ────────────────────────────────────────
  '操作事件': 'Events',
  '暂无事件': 'No events yet',
  '“应用后”与当前磁盘的差异':
    'Difference between “after apply” and the current disk',
  '比较中…': 'Comparing…',
  '重新比较': 'Compare again',
  '点击“重新比较”生成差异。': 'Click “Compare again” to generate a diff.',
  '（无法生成文本 diff）': '(no text diff available)',

  // ── 会话审阅：确认 / 操作 ────────────────────────────────────────
  '确认 hash 变化': 'Confirm hash changes',
  '以下文件在打包后被外部修改。应用补丁会以当前磁盘内容为基准；请确认你了解这一点。':
    'These files changed externally after packing. Applying patches will use the current disk content as the base; please confirm you understand this.',
  '确认并应用': 'Confirm and apply',
  '请至少勾选一个补丁': 'Select at least one patch',
  '补丁已应用，备份已写入': 'Patches applied; backups written',
  '有文件 hash 变化，需要逐项确认':
    'Some files changed on disk; confirm each one',
  '请确认所有 hash 变化的文件': 'Confirm every file whose hash changed',
  '已撤回最近一次应用': 'Reverted the last apply',
  '撤回会按备份恢复本批次修改过的文件，并删除新增文件。是否继续？':
    'Reverting restores the files changed in this batch from backup and deletes newly added files. Continue?',
  '撤回': 'Revert',
  '文件在应用后又被改过': 'Files changed again after applying',
  '以下文件与“应用后”不一致：\n{paths}\n\n确认仍按备份恢复吗？这会覆盖这些外部修改。':
    'These files differ from “after apply”:\n{paths}\n\nRestore from backup anyway? This overwrites those external changes.',
  '仍然撤回': 'Revert anyway',
  '归档会话': 'Archive session',
  '归档后会话目录会变成 zip 压缩包，列表仍可见。若仍有未撤回的应用，撤回时会先解压。':
    'Archiving turns the session folder into a zip; it stays visible in the list. If patches are still applied, reverting unpacks it first.',
  '仍有未撤回的补丁应用': 'Patches are still applied',
  '归档后如需撤回，PatchBridge 会先自动解压。确认归档吗？':
    'To revert later, PatchBridge unpacks the archive first. Archive anyway?',
  '仍然归档': 'Archive anyway',
  '会话已归档': 'Session archived',
  '删除会话': 'Delete session',
  '删除会话不会还原磁盘文件。确定删除这条历史记录吗？':
    'Deleting a session does not restore files on disk. Delete this history entry?',
  '删除会话不会影响磁盘上的代码，也不会自动撤回补丁。确认删除历史记录吗？':
    'Deleting a session does not change code on disk and does not revert patches. Delete this history entry?',
  '仍然删除': 'Delete anyway',
  '会话已删除': 'Session deleted',
  '标记后会话状态变为“已放弃”，可用于自动归档。不会修改磁盘文件。':
    'The session becomes “Abandoned”, which is eligible for auto-archive. Files on disk are not changed.',
  '标记放弃': 'Mark abandoned',
  '会话已标记为放弃': 'Session marked as abandoned',
  '已生成新会话，并重新校验 hash': 'New session created; hashes re-checked',
  '该会话没有记录用户 Prompt': 'No user prompt was recorded for this session',
  '没有待应用的补丁': 'No patches to apply',
  '全部补丁通过 dry-run': 'All patches passed dry-run',
  '有 {count} 个补丁存在冲突': '{count} patch(es) have conflicts',
  '{path} 可应用': '{path} can be applied',
  '{path} 无法应用': '{path} cannot be applied',
  '合并同文件补丁': 'Merge patches per file',
  '将把 {count} 个文件的多条 diff 合并成一条，并用合并结果替换原有补丁。\n如果多条 diff 修改了原文件的同一区域，会保留原样并提示。\n\n确认开始合并吗？':
    'This merges the diffs of {count} files into one diff per file and replaces the original patches with the merged result.\nIf several diffs touch the same region of a file, it is left as is and reported.\n\nStart merging?',
  '开始合并': 'Start merging',
  '已合并 {count} 组同文件 diff': 'Merged {count} group(s) of per-file diffs',
  '全部 {count} 组未合并：{paths}': 'All {count} group(s) failed to merge: {paths}',
  '已合并 {ok} 组，{failed} 组未合并：{details}':
    'Merged {ok} group(s); {failed} failed: {details}',
  'commit 建议': 'Commit suggestion',
  'commit 文本已保存': 'Commit message saved',

  // ── 历史 ──────────────────────────────────────────────────────────
  '会话历史': 'Session history',
  '所有会话均以纯文本保存，可按工程、状态、日期筛选。':
    'Every session is stored as plain text and can be filtered by project, status and date.',
  '索引不一致，重建': 'Index out of sync — rebuild',
  '检测到会话目录与索引不一致，已自动重建索引。':
    'The session folder was out of sync with the index; it was rebuilt automatically.',
  '索引已重建': 'Index rebuilt',
  '全部工程': 'All projects',
  '全部状态': 'All statuses',
  '全部存储': 'All storage',
  '未归档': 'Not archived',
  '搜索标题 / 工程 / ID': 'Search title / project / ID',
  '没有符合条件的会话。': 'No sessions match these filters.',
  '{count} 文件': '{count} files',
  '{count} 补丁': '{count} patches',
  '{count} 警告': '{count} warnings',
  '索引状态': 'Index status',

  // ── 设置 ──────────────────────────────────────────────────────────
  '这些设置对全部工程生效。': 'These settings apply to every project.',
  '大文件阈值（MB）': 'Large-file threshold (MB)',
  '超过该大小的文件默认不进入文件树，也不会被选中。':
    'Files larger than this are excluded from the tree and not selected by default.',
  '自动归档': 'Auto-archive',
  '启用自动归档（默认关闭）': 'Enable auto-archive (off by default)',
  '自动归档天数': 'Auto-archive after (days)',
  '只归档没有未撤回 apply、且状态为已撤回或已放弃、超过指定天数的会话。':
    'Only sessions with no unreverted apply and status reverted or abandoned, older than the given number of days, are archived.',
  '提示词模板路径': 'Prompt template path',
  '留空使用内置模板': 'Leave empty to use the built-in template',
  '模板支持': 'The template supports',
  '等占位符。': 'and other placeholders.',
  'Python 模式提示词模板路径': 'Python-mode prompt template path',
  '留空使用内置 Python SDK 模板':
    'Leave empty to use the built-in Python SDK template',
  'Python 脚本超时（秒）': 'Python script timeout (s)',
  '脚本 stdout 最大字符数': 'Max script stdout characters',
  'diff 默认上下文行数（0–50）': 'Default diff context lines (0–50)',
  'Python 脚本在独立线程中执行，只修改内存工作区；超时会丢弃结果，不会写真实文件。':
    'Python scripts run in a separate thread and only change the in-memory workspace; a timeout discards the result and never writes real files.',
  'mpatch 可执行文件': 'mpatch executable',
  '留空自动查找 mpatch 或 C:\\portable_apps\\bin\\mpatch.exe':
    'Leave empty to auto-detect mpatch or C:\\portable_apps\\bin\\mpatch.exe',
  '重新检测': 'Detect again',
  '严格引擎失败后，会自动在临时副本中调用 mpatch；真实工程目录不会交给 mpatch 写入。':
    'When the strict engine fails, mpatch runs on a temporary copy; mpatch never writes to the real project folder.',
  'mpatch 模糊相似度阈值（0–1）': 'mpatch fuzz similarity threshold (0–1)',
  '默认 0.7。越低越容易匹配，但误配风险也越高。':
    'Default 0.7. Lower values match more easily but raise the risk of wrong matches.',
  'mpatch 超时（秒）': 'mpatch timeout (s)',
  'AI 修正请求：整文件附加上限（字节）':
    'AI fix request: full-file attachment limit (bytes)',
  '文件不超过该值时附完整内容，否则只附失败位置附近的上下文。':
    'Files at or below this size are attached in full; larger files only include context around the failure.',
  'AI 修正请求：上下文行数': 'AI fix request: context lines',
  '备份保留天数': 'Backup retention (days)',
  '清理备份时不会删除仍有未撤回 apply 的备份。':
    'Cleanup never deletes backups that still have an unreverted apply.',
  '最大扫描文件数': 'Max scanned files',
  '单次打包大小上限（字节）': 'Max bundle size (bytes)',
  '设置已保存': 'Settings saved',
  '保存设置': 'Save settings',
};

let cached = null;

function normalize(locale) {
  const value = String(locale || '').toLowerCase();
  return SUPPORTED.has(value) ? value : DEFAULT_LOCALE;
}

function readStored() {
  try {
    return normalize(window.localStorage.getItem(LOCALE_KEY));
  } catch (err) {
    return DEFAULT_LOCALE;
  }
}

export function isSupportedLocale(locale) {
  return SUPPORTED.has(String(locale || '').toLowerCase());
}

export function getLocale() {
  if (cached === null) cached = readStored();
  return cached;
}

export function setLocale(locale) {
  cached = normalize(locale);
  try {
    window.localStorage.setItem(LOCALE_KEY, cached);
  } catch (err) {
    /* localStorage 不可用时只在本次页面内生效 */
  }
  applyDocumentLocale();
  return cached;
}

/**
 * 翻译界面文案。
 * @param {string} text 中文原文（词典 key）
 * @param {Record<string, unknown>} [params] 可选的 {name} 插值参数
 * @returns {string}
 */
export function t(text, params) {
  const source = text === null || text === undefined ? '' : String(text);
  const template =
    getLocale() === 'en' && Object.prototype.hasOwnProperty.call(DICT, source)
      ? DICT[source]
      : source;
  if (!params || typeof params !== 'object') return template;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match,
  );
}

/**
 * 保存语言并整页重载：hash 会保留，后端也会按新的 Accept-Language 重新出文案。
 * @param {'zh'|'en'} locale
 */
export function reloadWithLocale(locale) {
  setLocale(locale);
  // reload() 保留 pathname / query / hash，所以 #/session/xxx 之类的路由不会丢。
  window.location.reload();
}

/** 让 <html lang> 和 document.title 跟随当前语言。 */
export function applyDocumentLocale() {
  if (typeof document === 'undefined') return;
  const locale = getLocale();
  const root = document.documentElement;
  if (root) root.setAttribute('lang', locale === 'en' ? 'en' : 'zh-CN');
  document.title = TITLES[locale] || TITLES.zh;
}

/** 注册全局 $t，供所有组件模板使用。 */
export function installI18n(app) {
  if (app && app.config && app.config.globalProperties) {
    app.config.globalProperties.$t = t;
  }
  if (typeof window !== 'undefined') window.__pbT = t;
  applyDocumentLocale();
}
