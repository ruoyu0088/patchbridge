# PatchBridge

把 Web 版 AI 的回答安全地变成可审阅、可回滚的代码补丁。

PatchBridge 是一个**本地**工具：它不调用任何模型 API，也不做浏览器自动化。你负责在
PatchBridge 和 Web AI 之间手工复制文本；PatchBridge 负责收集上下文、打包、解析回答、
预览 diff、dry-run、备份、应用和撤回。

## 快速开始

```powershell
cd C:\Users\ruoyu\workspace\patchbridge
start.bat
```

Windows 下双击 `start.bat` 即可。服务器默认监听 `127.0.0.1:8765`，端口被占用时会
自动尝试后续端口，并打开浏览器。

其他平台：

```bash
cd patchbridge
PYTHONPATH=src python -m patchbridge --open
```

### 依赖

- Python 3.11+（开发环境为 3.14.8）
- FastAPI、Uvicorn、pathspec、charset-normalizer
- pytest、httpx（仅测试）
- Git 2.x（应用补丁时要求工程是 git 仓库）
- 可选：[mpatch](https://github.com/Romelium/mpatch) 1.8+（严格引擎失败后的模糊应用；
  默认查找 PATH 与 `C:\portable_apps\bin\mpatch.exe`，也可在设置中指定）
- 不需要 Node.js 运行时；Vue 3 运行时已内置在 `web/vendor/`

依赖已加入本机的 `C:\pixi_env`。换机器时：

```bash
pip install -e ".[test]"
```

## 工作流

1. **工程**：新建 profile，指定项目根目录和 gitignore 风格的文件范围。
2. **勾选文件**：搜索、勾选文件或目录；二进制文件、`.git/`、超阈值大文件默认排除。被排除的二进制文件路径会单独列出，点击可复制绝对路径。
3. **选择回答格式**：打包前选择 **Python 脚本**（默认、推荐）或 **Unified diff**。Python
   模式下 AI 调用内置补丁 API，不自己算行号或复制上下文；diff 模式兼容旧会话和外部工具。
4. **打包**：输入需求，生成打包文本。页面上同时提供：
   - **复制完整文本**：直接粘贴到 Web AI；
   - **复制文件路径**：在本地打开/上传 `bundle.txt` 文件。
5. **交给 AI**：内置提示词要求 AI 按“修改说明 / Commit 建议 / Python 脚本（或文件补丁）”回答。
6. **解析与执行**：把 AI 输出的全部内容粘贴回工具。Python 模式会自动提取脚本并在内存工作区执行，
   生成候选补丁；diff 模式自动寻找 unified diff。真实文件在应用前不会改变。Python 脚本页显示行号，
   执行步骤和错误位置可点击跳到对应脚本行；回答中的“Commit 建议”“Python 补丁脚本”等标题可以不带 `#`。
7. **审阅**：逐文件查看左右并排 diff（上下文行数可调）、状态、dry-run；可编辑补丁和 commit。
   冲突时可在编辑器中左右对照补丁上下文与当前文件，定位缩进/内容差异；纯缩进冲突可一键对齐。
8. **模糊回退**：严格引擎失败时自动对齐纯缩进，再在**临时副本**中调用 mpatch；成功后展示由副本
   `git diff` 生成的最终补丁，应用前仍由严格引擎校验。仍失败则生成一段“AI 修正请求”
   （小文件附全文，大文件附失败位置附近 ±30 行），复制回 Web AI 重新生成。
9. **应用**：勾选文件，部分应用；应用前自动备份。
10. **撤回**：严格 LIFO，按备份恢复修改过的文件，删除新增文件。
11. **历史**：纯文本会话、索引、归档、导出、重新载入。

更详细的步骤见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)。

## 示例

- [examples/example.profile](examples/example.profile)
- [examples/demo-project](examples/demo-project)
- [examples/sample-session](examples/sample-session)：脱敏的已解析会话，可直接查看
  `bundle.txt`、`answer.md`、`parsed.json`、`patches/` 和 `events.jsonl`。

## 数据目录

默认在项目根目录的 `data/`，可用 `PATCHBRIDGE_DATA_DIR` 覆盖：

```text
data/
  settings.json
  index.json
  profiles/*.profile
  sessions/<id>/...
    script/script.py|report.json
    mpatch/<patch_id>.json|.patch|.repair.md
  sessions/<id>.zip
  backups/<id>/<apply_id>/...
  tmp/
  logs/app.log
```

全部使用纯文本/JSON/JSONL，不使用数据库。`data/` 已加入 `.gitignore`。

## 测试

```powershell
$env:MKL_THREADING_LAYER='TBB'
& "C:\pixi_env\.pixi\envs\default\python.exe" -m pytest
```

其他环境把解释器换成自己的 Python 3.11+ 即可。

测试覆盖 profile 规则、打包冲突、解析容错、diff 应用、CRLF/BOM、部分应用、LIFO 撤回、
索引重建、归档、恶意 zip、导出 patch 在干净 git 副本上的应用，以及 mpatch 副本隔离、
模糊应用、失败修正请求和编码保持。Python 模式另有打包头、脚本解析、内存执行、预期数
不匹配、越界路径、新建文件、语法错误、BOM/CRLF 和 API 流程测试。逐条验收映射见
[docs/ACCEPTANCE_MATRIX.md](docs/ACCEPTANCE_MATRIX.md)。

## 重要限制

- 只处理文本补丁；删除文件、重命名、文件权限修改、二进制补丁会被拒绝。
- Python 模式只能修改本次选中的文件，或新建 profile 可见范围内尚不存在的文件；不能删除/重命名，
  也不能整文件覆盖。脚本在受限线程中运行，超时会丢弃该次内存工作区。
- v1 只支持文件级勾选，不支持 hunk 级勾选。
- 应用补丁要求工程是 git 仓库（内部使用字节安全的行级引擎，不依赖 `git apply` 写盘）。
- mpatch 是可选外部依赖；未安装时只使用严格引擎和缩进对齐，失败后直接生成修正请求。
  mpatch 命令行按 UTF-8 读取副本；PatchBridge 会先把副本规范化为 UTF-8/LF，最终仍由严格引擎
  按原编码/BOM 写回。
- 工具只监听本机回环地址，没有登录/多用户机制。
- 备份保留期过后，“应用后 vs 当前磁盘”的内容差异可能不可用。

完整设计决策与平台说明见 [docs/DESIGN.md](docs/DESIGN.md)。

## 目录

```text
src/patchbridge/   后端与核心逻辑
web/               无构建 Vue 界面
tests/             自动化测试
examples/          示例 profile、demo 工程、脱敏会话
docs/              设计、用户指南、验收矩阵
start.bat          Windows 双击启动
```
