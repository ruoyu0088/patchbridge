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
- 不需要 Node.js 运行时；Vue 3 运行时已内置在 `web/vendor/`

依赖已加入本机的 `C:\pixi_env`。换机器时：

```bash
pip install -e ".[test]"
```

## 工作流

1. **工程**：新建 profile，指定项目根目录和 gitignore 风格的文件范围。
2. **勾选文件**：搜索、勾选文件或目录；二进制文件、`.git/`、超阈值大文件默认排除。
3. **打包**：输入需求，生成打包文本。页面上同时提供：
   - **复制完整文本**：直接粘贴到 Web AI；
   - **复制文件路径**：在本地打开/上传 `bundle.txt` 文件。
4. **交给 AI**：使用内置提示词要求 AI 按“修改说明 / Commit 建议 / 文件补丁”回答。
5. **解析**：把 AI 输出的全部内容粘贴回工具；工具自动寻找 unified diff。
6. **审阅**：逐文件查看 diff、状态、dry-run；可编辑补丁和 commit。冲突时可在编辑器中左右对照补丁上下文与当前文件，定位缩进/内容差异；纯缩进冲突可一键对齐。
7. **应用**：勾选文件，部分应用；应用前自动备份。
8. **撤回**：严格 LIFO，按备份恢复修改过的文件，删除新增文件。
9. **历史**：纯文本会话、索引、归档、导出、重新载入。

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
索引重建、归档、恶意 zip、导出 patch 在干净 git 副本上的应用等。逐条验收映射见
[docs/ACCEPTANCE_MATRIX.md](docs/ACCEPTANCE_MATRIX.md)。

## 重要限制

- 只处理文本补丁；删除文件、重命名、文件权限修改、二进制补丁会被拒绝。
- v1 只支持文件级勾选，不支持 hunk 级勾选。
- 应用补丁要求工程是 git 仓库（内部使用字节安全的行级引擎，不依赖 `git apply` 写盘）。
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
