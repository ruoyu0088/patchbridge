# PatchBridge 设计说明

## 1. 目标与边界

PatchBridge 解决的是“代码量大时，让 Web 版 AI 改几行代码”的上下文搬运问题：

- 工具不调用任何在线模型 API。
- 工具不做浏览器自动化。
- 用户在工具和 Web AI 之间手工复制。
- 工具负责：profile 过滤、文件树、打包、回答解析、补丁预览、dry-run、备份、应用、撤回、
  历史、归档。

应用补丁要求工程位于 git 仓库中；工具会检查 `git rev-parse --is-inside-work-tree`。
实际写盘使用内置事务式行级引擎，以保证 CRLF/BOM/编码可控；导出的标准 patch 仍可用
`git apply` 验证和应用。严格引擎失败时，可自动在临时副本中调用外部 mpatch 做相似度匹配，
但最终写盘仍回到严格引擎，mpatch 永远不直接接触真实工程目录。

## 2. 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11+、FastAPI、Uvicorn | 单进程本地 HTTP 服务 |
| 前端 | Vue 3 全局运行时 + 原生 CSS | 无构建、离线可用 |
| 文件匹配 | pathspec | gitignore 语义，支持 `!` 取反 |
| 编码检测 | charset-normalizer | 非 UTF-8 文本的保守检测 |
| 测试 | pytest + FastAPI TestClient | 核心逻辑无 GUI 可测 |
| 存储 | 纯文本 + JSON + JSONL | 不使用数据库 |

## 3. 运行形态

- 默认绑定 `127.0.0.1:8765`，端口冲突时顺序尝试后续端口。
- 单进程、单用户。按会话/文件系统操作加锁。
- `start.bat` 设置 `MKL_THREADING_LAYER=TBB` 并使用 `C:\pixi_env` 的解释器；找不到时回退
  到 PATH 上的 `python`。
- 所有文件系统写操作都在后端；前端只通过 JSON API 操作。

## 4. 数据目录

```text
data/
  settings.json
  index.json
  profiles/<id>.profile
  sessions/<session_id>/
    meta.json
    requirement.md
    selection.json
    bundle.txt
    answer.md
    parsed.json
    patches/
      manifest.json
      p0001.diff
    script/
      script.py
      report.json
    mpatch/
      p0001.json
      p0001.patch
      p0001.repair.md
    events.jsonl
  sessions/<session_id>.zip
  backups/<session_id>/<apply_id>/
    manifest.json
    before/0000.bin
    after/0000.bin
    combined.patch
    journal.json
  tmp/
  logs/app.log
```

### 4.1 Profile

纯文本、应用管理，语法：

```ini
# PatchBridge profile v1
name: 示例工程
root: C:\Users\me\project
mode: exclude

[rules]
.git/
node_modules/
*.log
!keep.log
```

- `root` 必须是绝对路径；允许 `~` 展开。
- `mode`：
  - `exclude`：默认可选，规则命中则排除；`!` 再纳入。
  - `include`：只有规则命中的文件才可选；`!` 再排除。
- 规则按 gitignore 语义，最后匹配优先。
- `.git/`、`.hg/`、`.svn/` 永远跳过；工具数据目录若位于工程内也会跳过。
- 根目录不可访问时工程仍显示，但禁止扫描和打包。

### 4.2 打包文本

固定分隔符，包含相对路径：

```text
# PATCHBRIDGE BUNDLE v1
MODE: python
project: ...
root: ...
generated_at: ...
files: 3
bytes: 12345

===== PATCHBRIDGE INSTRUCTIONS BEGIN =====
...
===== PATCHBRIDGE INSTRUCTIONS END =====

===== PATCHBRIDGE TREE BEGIN =====
...
===== PATCHBRIDGE TREE END =====

===== PATCHBRIDGE REQUIREMENT BEGIN =====
...
===== PATCHBRIDGE REQUIREMENT END =====

===== PATCHBRIDGE FILE BEGIN: src/app.py =====
<原始内容>
===== PATCHBRIDGE FILE END: src/app.py =====
```

- 文件内容不做转义、缩进调整或换行归一化。
- 文件末尾没有换行时，仅插入一个结构性换行让结束标记独立成行；
  `selection.json` 记录 `final_newline:false`。
- 打包前扫描需求和文件内容中的保留标记；发现冲突则拒绝并列出文件。
- `selection.json` 保存每个文件的 `sha256`、编码、BOM、EOL、末尾换行信息。
- token 数是粗略提示（ASCII 约 4 字符/token，非 ASCII 约 1 字符/token），不是硬限制。

**给 AI 的两种方式**：界面同时提供“复制完整文本”和“复制文件路径”。前者适合直接粘贴；
后者用于在本地打开或上传 `bundle.txt`。

### 4.3 回答解析

打包前在 `MODE: python|diff` 中选择回答格式，并写入 `bundle.txt` 与 `selection.json`；默认 Python。

Python 模式内置提示词要求：

````markdown
## 修改说明
## Commit 建议
## Python 补丁脚本
```python
replace_text("src/app.py", "old", "new", expected=1)
```
````

diff 模式内置提示词要求：

````markdown
## 修改说明
## Commit 建议
## 文件补丁
### src/app.py
```diff
...
```
````

Python 模式解析器提取第一个 Python 代码块；没有代码块时，兼容旧回答按 diff 解析并给出 warning。
diff 模式解析器容错：

- 中英文标题、关键词、缺少标题都尽量识别。
- 代码块有无语言标记都可。
- 无代码围栏时扫描 `diff --git` / `---`/`+++` / `@@`。
- 路径支持 `a/`、`b/`、绝对路径、反斜杠、标题路径。
- 自动计算原始 `-pN`，规范化成 `p1`。
- 拒绝 `..`、绝对路径越界、`.git/`、重复路径和删除/重命名/二进制补丁。
- 所有不确定处写入 warnings；解析结果可手工修改。

### 4.4 会话与事件

- 会话 ID 是时间有序字符串，唯一。
- `patches/manifest.json` 显式记录存储文件名与相对路径的映射，禁止根据文件名反推路径。
- `events.jsonl` 只追加，事件类型包括 `pack`、`parse`、`dry_run`、`apply`、`revert`、
  `archive`、`reload`、`edit`、`abandon`、`apply_failed`。
- `meta.json` 中的状态是缓存；列表状态由事件和 parsed 是否存在推导。
- `index.json` 是缓存，写入使用临时文件 + `os.replace` + fsync；启动和列表时校验，
  发现目录/压缩包集合与索引不一致会自动重建，也可手动重建。

### 4.5 备份与状态机

应用前为每个受影响文件保存：

- 原始相对路径
- 备份文件位置
- 应用前是否存在
- 应用前 sha256
- 应用后 sha256
- 文件 mode（如可读取）
- 应用后内容（用于“应用后 vs 当前磁盘”比较）

状态：

```text
packed -> parsed -> applied -> reverted
                    |  ^
                    |  └── 其他未应用文件可继续按批次 apply
                    └── 首次 apply 后补丁/commit 锁定
```

- 每批 apply 是一个事务，事件中记录批次 `apply_id`。
- 同一文件在一个会话中最多应用一次。
- 部分应用后，剩余文件仍可再次 apply，但补丁内容不可再编辑。
- 撤回严格 LIFO：只能撤回最后一个未撤回批次。
- 需要修改已应用补丁时，使用“重新载入”创建新会话。
- 撤回时若文件当前内容与应用后不一致，必须显式确认；确认后按备份恢复。

### 4.6 补丁引擎

文件行模型：

- 原始每行 EOL 保留；新行使用文件主 EOL。
- UTF-8/UTF-16 的 BOM 保留；其他编码通过 charset-normalizer 保守检测，无法无损往返则按
  不支持文本处理。
- hunk 上下文精确匹配；找不到时在文件中搜索唯一/最近匹配并记录 offset warning。
- 支持新增文件；不支持删除、重命名、mode 变更、二进制补丁。
- 应用前全部在内存试算，然后备份、写 journal、逐文件原子替换；任一失败按备份整体回滚。
- 启动时扫描未完成 journal：若 apply 事件尚未落盘则回滚，若事件已落盘则只清理 journal。

### 4.7 mpatch 模糊回退

每次 `evaluate_patch` 按以下顺序尝试，全部自动执行：

1. 严格行级引擎（原行为）；
2. 严格失败时尝试 `align_patch_indentation`，只接受每个 hunk 一个统一的空格/Tab 偏移；
3. 对齐仍失败或对齐后严格重试仍失败，调用外部 mpatch。

mpatch 的隔离方式：

- 每个文件在 `data/tmp/` 下建立一次性副本，只把副本路径交给 mpatch；真实工程目录从不作为
  mpatch 的 target。
- 副本统一规范化为 UTF-8/LF，mpatch 以 `-n -a -f <threshold>` 先 dry-run 再应用；
  然后只允许目标文件发生变化，用 `git diff --cached` 生成标准 unified diff。
- 该 diff 会重新解析，并用严格引擎在真实文件的当前内容上再应用一次；只有这一步成功，
  结果才标记为可应用。因此 CRLF/BOM/原编码仍由现有编码层保持。
- 原始补丁文本不改；`Evaluation.final_patch` 保存派生结果，`apply_session` 合并时优先使用它。
- 首次应用后仍然锁定原始补丁；需要改补丁必须“重新载入”。

失败时：

- 解析 stderr 中的 `Hunk N failed`、最佳匹配行号/相似度、near-miss、ambiguous 等信息；
- 生成 `<patch_id>.repair.md`：小文件附完整当前文件，大文件附失败行附近上下文；
- 返回 `待 AI 修正`，不自动应用，也不修改原补丁；
- 用户可复制修正请求回 Web AI，或继续使用手工编辑器。

工件（`sessions/<id>/mpatch/`）：

- `<patch_id>.json`：状态、原因、原始/当前/最终补丁 hash、诊断、mpatch 版本与耗时；
- `<patch_id>.patch`：mpatch 生成的最终补丁（仅成功时）；
- `<patch_id>.repair.md`：修正请求（仅失败时）。

任何补丁编辑、合并、重新解析都会使该补丁的 mpatch 工件失效，避免把旧结果应用到新补丁。
归档 zip 内保持同样结构；查看归档会话时按 member 读取，不整体解压。

### 4.8 归档

- 归档 zip 的条目是相对于会话目录的路径，结构与未归档目录一致。
- 拒绝绝对路径、盘符、`..`、反斜杠、符号链接、重复条目和超限解压体积。
- 查看归档详情时按 member 读取，不整体解压。
- 撤回/应用等 mutation 会先把 zip 安全解压回会话目录。
- 重新载入从 zip 按 member 读取并创建新会话，不修改原会话。
- 自动归档默认关闭；只处理没有未撤回 apply、状态为 `reverted` 或 `abandoned` 且超过
  指定天数的会话。手动归档有未撤回 apply 时要求二次确认。

### 4.9 Python 脚本模式

AI 不再输出 diff，而是输出一段只调用 PatchBridge 补丁 API 的 Python 程序。目标是把“算行号、
复制上下文、处理编码/EOL”从模型输出中移除，只保留“改什么”。

**内存工作区**

- 执行开始时所有选中文件读入 `Workspace`，每个文件保存 `original_text`（运行开始时的磁盘内容）、
  `current_text`、编码/BOM/EOL/final_newline；打包快照的 sha256 仍在应用前校验。
- API 只修改内存中的 `current_text`；脚本不能直接读写文件，也没有 `open`/`os`/`pathlib`。
- 运行结束后逐个文件比较 original/current；有变化的文件用 `difflib.unified_diff` 生成文本 diff，
  再交给现有 `parse_unified_diff` → `ParsedPatch`，后续 dry-run/apply/备份/撤回完全复用。
- 新增文件生成 `/dev/null` 风格的补丁；删除/重命名/权限修改不提供 API。

**API 语义**

- 定位：`read_text`、`count`、`replace_text`、`replace_regex`、`insert_before`、`insert_after`、
  `replace_between`、`create_file`。
- 校验：`assert_count`、`assert_contains`、`assert_not_contains`、`assert_python_syntax`。
- 每个修改 API 必须传 `expected`（预期匹配数）。实际数不符时按实际匹配执行并记录 warning，
  不静默跳过；`limit` 可限制单次替换数。
- 顺序执行，后一步看到前一步的 `current_text`；`replace_between` 要求锚点对唯一。
- 运行时异常保留异常前的部分修改并生成部分补丁；超时丢弃整个运行结果；语法错误不生成补丁。
- 只能改本次选中文件或新建 profile 可见且尚不存在的文件；路径必须相对、不能越界。

**受限执行**

- 使用 `exec` + 自定义 builtins，允许 `re, collections, itertools, functools, math, json,
  textwrap, string, difflib, typing, dataclasses`，屏蔽 `open/eval/exec/compile/__import__/...`。
- 在 daemon 线程中执行，`sys.settrace` 检查 deadline；超时只能停止 Python 字节码，不能抢占
  C 扩展调用，因此超时结果整体丢弃，绝不读取可能仍在变化的内存工作区。
- 脚本 stdout 截断到设置上限；步骤、warning、stdout、异常写入 `script/report.json`。

**存储与 UI**

- 会话 `meta.json`/`selection.json` 记录 `mode`；`script/script.py` 保存最后执行的脚本，
  `script/report.json` 保存执行报告；补丁仍存 `patches/`。
- 审阅页提供“Python 脚本”标签，可编辑并重新执行；粘贴回答时自动执行一次。
- diff 预览由 `diff_view.build_diff_rows` 生成左右并排行，按上下文行数裁剪；原始 unified diff
  保留在折叠区。
- 归档 zip 内结构相同，读取脚本/报告按 member 流式读取。

## 5. 安全底线

1. 所有写操作只在后端。
2. apply 前重新 dry-run + 校验 hash/范围/git 仓库；hash 变化需显式确认。
3. 应用前备份；新增文件撤回删除。
4. 撤回 LIFO + after hash 校验。
5. 编码、BOM、换行保持。
6. mpatch 只在临时副本运行；临时目录无论成功/异常都清理；最终写盘前重新严格校验。
7. zip 解压安全，临时目录异常清理。
8. 事件只追加；meta/index/settings 原子写。
9. 全局异常处理返回结构化 JSON，不把堆栈抛给前端。
10. 解析结果允许手工修正。
11. Python 脚本只在内存工作区执行，不暴露文件系统对象；导入和 builtins 白名单；
    超时丢弃结果，异常只保留部分内存修改。最终仍走“生成补丁 → dry-run → 备份 → 应用”链路。
12. 绑定回环地址；无公网认证设计。

## 6. 已知限制

- v1 不做 hunk 级勾选。
- 只支持文本补丁；删除/重命名/二进制/权限补丁拒绝。
- 应用要求 git 仓库；内部引擎不依赖 `git apply` 写盘。
- 非 UTF-8 编码依赖启发式检测；检测不确定时按二进制/不支持处理。
- mpatch 是可选外部依赖，且其 CLI 按 UTF-8 读取副本；PatchBridge 会先把副本规范化为 UTF-8/LF，
  最终仍由严格引擎按原编码/BOM 写回。无法可靠识别的文本才会被拒绝。mpatch 的超时、崩溃或
  不兼容输出一律视为“未命中”，不会写入真实工程。
- 备份过期后“应用后 vs 当前磁盘”的内容差异不可用。
- 跨会话撤回冲突依靠 hash 校验和用户确认，不实现全局应用栈。
- 本地单用户工具，不适合直接暴露到公网。
- 大工程扫描有 `max_files` 上限；超过时收窄 profile。
- Python 模式只支持选中文件内的文本修改和新建文件；不支持删除/重命名/整文件覆盖。
  超时无法抢占 C 扩展，只能丢弃本次内存工作区并保留上一次成功补丁。
- Python 脚本受白名单限制，不适合需要第三方库或复杂重构的任务；此类任务仍可用 diff 模式。

## 7. 平台依赖

| 平台 | 启动 | 依赖 |
|---|---|---|
| Windows 10/11 | 双击 `start.bat` | Python 3.11+、Git、依赖包；可选 mpatch 1.8+ |
| macOS / Linux | `PYTHONPATH=src python -m patchbridge --open` | Python 3.11+、Git、依赖包；可选 mpatch 1.8+ |

`start.bat` 使用 CRLF 换行，并优先使用 `C:\pixi_env\.pixi\envs\default\python.exe`。
前端 Vue 运行时已 vendored，不需要联网或 Node 构建。

## 8. 测试策略

- 单元：profile、扫描、打包、解析、diff、编码、zip 安全。
- 集成：会话、索引、备份、部分应用、LIFO 撤回、归档、重新载入。
- mpatch：副本隔离、模糊应用、失败修正请求、缩进先行、BOM/CRLF 保持。
- Python 模式：bundle mode 头、脚本/回答解析、内存 API、expected 不符、越界路径、新建文件、
  语法错误/超时、BOM/CRLF 保持、并排 diff 行结构。
- 端到端：FastAPI 流程、导出 patch 在干净 git 副本上 `git apply`。
- 前端：人工冒烟；核心逻辑不依赖浏览器。
- 逐条验收映射见 `docs/ACCEPTANCE_MATRIX.md`。
