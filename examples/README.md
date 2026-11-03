# 示例

## `example.profile`

一个使用 `examples/demo-project` 作为根目录的 profile。仓库移动后请修改 `root` 为
新的绝对路径。

## `demo-project`

一个非常小的 Python 工程，用来演示文件树和补丁流程。它本身没有嵌套 Git 仓库；
需要测试应用补丁时，请复制到临时目录并执行 `git init`。

## `sample-session`

脱敏的示例会话，包含：

```text
meta.json
requirement.md
selection.json
bundle.txt
answer.md
parsed.json
patches/manifest.json
patches/p0001.diff
events.jsonl
```

它对应“给 divide 增加除零保护”的需求，包含一次 dry-run 事件，没有应用补丁。

如果希望在本机历史列表中打开它，把整个目录复制到：

```text
data/sessions/sample-session/
```

然后刷新“历史会话”页面。目录名与 `meta.json` 中的 `id` 一致。
