## 修改说明
为 divide 增加除零保护：当 right 为 0 时返回 None，避免抛出 ZeroDivisionError。该行为适用于整数和浮点数，不改变其他分支。

## Commit 建议
fix(calculator): guard division by zero

## 文件补丁

### src/calculator.py
```diff
diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -9,2 +9,4 @@
 def divide(left: float, right: float) -> float:
+    if right == 0:
+        return None
     return left / right
```
