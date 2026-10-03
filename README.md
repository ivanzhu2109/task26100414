# flowguard

进程内流量防护规则匹配库（纯 Python 标准库，无外部依赖）。规则与检查状态仅保存在进程内存中，
供上层检测流程调用：采集器分段交付字段原始字节，结束检查时按**最左最长**原则返回每条命中规则的证据区间。

## 能力

- 规则集 `RuleSet`：加载带唯一标识的规则（重复标识抛 `ValueError`），可复用于多次检查。
- 检查会话 `CheckSession`：`append(chunk)` 逐段追加字节（空片段不表示结束），`finish()` 结束检查并返回命中证据。
- 模式语法（Python 字节正则子集，ASCII）：字面量、元字符转义、`\xHH`、`.`（匹配任意字节含换行与零字节）、
  字符集合 `[...]`（范围与取反 `[^...]`）、分组 `(...)`、选择 `|`、量词 `* + ?`、首尾锚点 `^ $`。
- 锚点语义：`^` 仅匹配整个字段开头；`$` 仅匹配真正的字段结束（不匹配末尾换行之前）。片段边界不是字段边界。
- 证据语义：最左最长——起点最小优先，同起点取终点最大；区间 `[start, end)` 从零开始按字节计；
  空串匹配允许 `start == end`；未命中的规则不返回证据。与切分方式、规则装载顺序无关。

## 用法

```python
from flowguard import RuleSet

rs = RuleSet()
rs.add_rule("cmd-injection", r"\x00|/bin/sh")
rs.add_rule("header-shape", "^Host:[^\\r]+\\r$")

session = rs.begin()
for chunk in collector_chunks:   # 任意切分，允许空片段
    session.append(chunk)
for ev in session.finish():      # [Evidence(rule_id=..., start=..., end=...), ...]
    report(ev)
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

`tests/reference.py` 是独立的参考实现（自带解析器 + 集合语义求值），
测试用它对空串循环、多分支、随机模式与随机切分做交叉验证。
