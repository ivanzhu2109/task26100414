# flowguard — 流量防护规则匹配库

纯 Python 标准库实现的字节级正则规则匹配库，供上层检测流程调用。
规则与检查状态仅保存在进程内存中，无任何外部依赖与服务。

## 功能

- 规则集加载：每条规则带唯一标识，可编译复用于多次字段检查。
- 分段检查：`feed()` 追加原始字节片段，`finish()` 结束并返回证据。
  片段边界（含空片段）不影响结果；同一字段无论如何切分，证据完全一致。
- 模式语法（ASCII，Python 字节正则子集）：字面量、元字符转义、
  `\xHH`、`.`（匹配任意字节，含换行与零字节）、字符集合 `[...]`
  （范围与取反）、分组 `(...)`、选择 `|`、量词 `*` `+` `?`、
  首尾锚点 `^` `$`（`$` 只匹配真正的字段结束，不匹配末尾换行之前）。
- 证据区间：按最左最长原则选择（起点最小优先，同起点取终点最大），
  半开区间 `[start, end)`，从零开始按字节计。未命中的规则不返回证据。

## 用法

```python
from flowguard import RuleSet

rules = RuleSet()
rules.load([
    ("uri-admin", b"^/admin(/|$)"),
    ("ua-badbot", b"[Bb]ad[Bb]ot\\+\\d"),
    ("hex-bytes", b"\\x00\\xff"),
])

session = rules.begin()      # 开始一个字段的检查
session.feed(b"/adm")        # 采集器分段交付
session.feed(b"")
session.feed(b"in/panel")
result = session.finish()    # -> {"uri-admin": (0, 11)}
```

## 运行测试

```sh
python3 -m unittest discover -s tests -v
```

测试覆盖：最左最长语义（含 `a|aa` 等分支顺序无关用例）、空串循环与
空模式、锚点与末尾换行、任意切分点与空片段的切分不变性、规则装载
顺序无关性，以及与基于 `re` 的独立全字段参考计算的差分对比
（固定样例 + 随机生成用例）。

## 实现说明

- `flowguard/parser.py`：模式子集的递归下降解析，产出 AST。
- `flowguard/nfa.py`：Thompson 构造编译为 NFA，单次扫描模拟，
  按线程起点追踪实现最左最长；空循环由闭包 visited 集合防护。
- `flowguard/rules.py`：`RuleSet` / `CheckSession` 公开 API；
  会话缓冲片段，`finish()` 时对每条规则独立求值。
