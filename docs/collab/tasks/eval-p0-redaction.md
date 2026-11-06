# EVAL-P0 任务卡：还清产品→评测的反向依赖

| 项 | 值 |
|---|---|
| 工作包 | EVAL-P0 |
| 状态 | `ready` |
| 负责人 | ZCode |
| 仓库 | **产品仓** `C:\Users\Administrator\Desktop\CloudAgent-public` |
| 分支 | `feat/eval-p0-redaction` |
| 预估 | **30 分钟** |
| 依赖 | 无。**建议在 P1 合并后立刻做**（改动小、风险低） |

> 设计依据：[`../design/eval-system-design.md`](../design/eval-system-design.md) §8 P0
> 这是整个评测体系拆分的**第一步**，也是唯一一步"必须先做否则后面都建在沙子上"的事。

## 问题

```python
# cloudagent_ext/diagnosis/log/tools.py:41
from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive
```

**产品代码 import 了评测代码。** 这是分层倒置：

- 正常方向：评测 → 产品（下游依赖上游）
- 现在方向：产品 → 评测（上游依赖下游）

后果：
1. **删不掉 `evaluation/`**（删了产品就崩）；
2. "评测是独立项目"这句话**名不副实**；
3. 一旦评测仓拆出去，产品仓会出现一个**悬空依赖**。

## 为什么这条容易修

`redact_sensitive` 本身**不是评测逻辑**——它是通用文本脱敏（DSN / 密码 / API Key /
手机号 / 邮箱）。评测报告和日志工具**共用同一个函数**是合理的（避免规则漂移），
只是它**放错了位置**。

实测：脱敏实现（`_DSN_PATTERN` / `_PASSWORD_ASSIGN` / `_KEY_PREFIX` /
`_PHONE_PATTERN` / `_EMAIL_PATTERN` + `_redact_dsn` / `redact_sensitive` /
`redact_payload`）在 `report.py` 里共 **69 行**。

## 写入范围

```
cloudagent_ext/utils/redaction.py            （新增：脱敏实现迁入）
cloudagent_ext/diagnosis/evaluation/report.py（改为 re-export，保持向后兼容）
cloudagent_ext/diagnosis/log/tools.py        （改 import 路径）
tests/utils/test_redaction.py                （新增：脱敏规则的单测）
docs/collab/handoffs/eval-p0-redaction.md    （新增）
```

**不许动**：脱敏**规则本身**（正则一个字都不许改）、`report.py` 的其它函数、
`evaluation/` 下其它模块的行为。

## 具体改法

### 1. 新建 `cloudagent_ext/utils/redaction.py`

把这 69 行**原样搬过去**（含全部正则与两个函数），文件头写清来由：

```python
"""通用文本脱敏（DSN / 密码 / API Key / 手机号 / 邮箱）。

**为什么在 utils 而不是 evaluation**：日志工具（产品）与评测报告（评测）
共用同一套脱敏规则，避免规则漂移。原实现在
``diagnosis/evaluation/report.py``，属分层倒置（产品 import 评测），
EVAL-P0（2026-11-07）迁到此处。
"""

__all__ = ["redact_sensitive", "redact_payload"]
```

### 2. `report.py` 改为 re-export（**不删原函数**）

```python
# report.py 顶部
from cloudagent_ext.utils.redaction import redact_payload, redact_sensitive  # noqa: F401
```

⚠️ **关键**：`report.py` 的 `__all__` 仍要含这两个名字。
原因：`evaluation/` 里还有其它模块（`executors.py` / `runner.py` / `safety.py`）
从 `report` import 它们。**保持向后兼容**，这样本卡不需要改那些文件，
diff 最小、风险最低。

### 3. `log/tools.py:41` 改一行

```python
# 改前
from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive
# 改后
from cloudagent_ext.utils.redaction import redact_sensitive
```

### 4. 新增 `tests/utils/test_redaction.py`

**不是可选的**。把脱敏规则从"只在评测链路里被间接用到"变成"有直接单测"。
至少覆盖：

| case | 输入 | 期望 |
|---|---|---|
| DSN | `postgresql://user:pass@host:5433/db` | `postgresql://user:***@host:5433/db` |
| 已脱敏的 DSN | `postgresql://user:***@host/db` | **保持不变**（幂等） |
| 密码赋值 | `password=secret123` | `password=***` |
| API Key | `sk-abcdef123456` | `***` |
| 手机号 | `13800138000` | `1**********` |
| 邮箱 | `alice@example.com` | `***@***` |
| 空串 | `""` | `""` |
| **JSON 语法不被破坏** | `{"a": "postgresql://u:p@h/d"}` 走 `redact_payload` 后仍可 `json.loads` | 可解析 |

最后一条尤其重要——`redact_payload` 的 docstring 里已经解释了
"为什么不能对 `json.dumps` 结果直接跑正则"，这条要守住。

## 验收命令

```powershell
# ① 反向依赖清零（本卡存在的理由）
#    注意：evaluation/ 自身内部互相引用是正常的，必须排除，否则会误报 5 条。
python -c "
import glob, os
hits = []
for f in glob.glob('cloudagent_ext/**/*.py', recursive=True):
    if '__pycache__' in f:
        continue
    if os.path.normpath(f).startswith(os.path.normpath('cloudagent_ext/diagnosis/evaluation')):
        continue
    if 'diagnosis.evaluation' in open(f, encoding='utf-8', errors='ignore').read():
        hits.append(f)
print('产品侧残留反向依赖：', hits)   # 期望：[]
"
# 2026-11-07 实测（修前）：['cloudagent_ext\\\\diagnosis\\\\log\\\\tools.py']

# ② 新单测
python -m pytest tests/utils/test_redaction.py -q

# ③ 脱敏行为不变（日志域与评测报告都依赖它）
python -m pytest tests/diagnosis/test_report_redaction.py -q
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 期望：836 passed / 24 skipped（P1 合并后基线），只增不减

# ④ 日志工具仍可用
python -m pytest tests/diagnosis/log -q --no-header -p no:cacheprovider

# ⑤ lint
python -m ruff check cloudagent_ext/utils/redaction.py cloudagent_ext/diagnosis/evaluation/report.py cloudagent_ext/diagnosis/log/tools.py
```

## 完成定义

- [ ] `cloudagent_ext/utils/redaction.py` 存在，含 `redact_sensitive` + `redact_payload`，**正则与原实现逐字一致**
- [ ] `log/tools.py` 不再 import `diagnosis.evaluation`
- [ ] **反向依赖扫描结果为空**（这是本卡的核心验收，命令见上）
- [ ] `report.py` 仍 re-export 两个函数，`evaluation/` 下其它模块**零改动**且测试全绿
- [ ] `tests/utils/test_redaction.py` 覆盖上表 8 类，含"JSON 语法不被破坏"
- [ ] `tests/diagnosis` 无回归；`tests/diagnosis/test_report_redaction.py` 全绿
- [ ] handoff 写：确认脱敏规则一个字没改、只搬位置

## 红线

1. **不许改脱敏规则**。本卡是搬家，不是改进。想改进规则 → 另开任务。
2. **不许删 `report.py` 里的 re-export**。它是 `evaluation/` 内部模块的兼容层，
   删了会连带改 4 个文件，超出本卡范围。
3. **不许顺手删 `evaluation/` 下任何文件**。整个 `evaluation/` 的删除属 EVAL-P1b/P2，
   且必须先完成迁移。
4. 如果发现除 `log/tools.py` 之外**还有**产品代码 import `diagnosis.evaluation`，
   **停下来报告**——说明我漏了使用点，需要重新评估范围。
