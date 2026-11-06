# EVAL-P0 交接说明：还清产品→评测的反向依赖

> ZCode · 2026-11-07 · 分支 `feat/eval-p0-redaction`

## 改了什么

| 文件 | 改动 |
|---|---|
| `cloudagent_ext/utils/redaction.py`（新增） | 脱敏实现从 `evaluation/report.py` **原样迁入**（5 条正则 + `_redact_dsn` + `redact_sensitive` + `redact_payload`，共 1888 字符块逐字搬运），文件头注明迁库缘由 |
| `cloudagent_ext/diagnosis/evaluation/report.py` | 脱敏块替换为对 `utils.redaction` 的 re-export；`__all__` 原样保留两个名字；顺带移除因此空置的 `import re`（块内 7 处 `re.*` 是它的唯一使用方，不删会 F401） |
| `cloudagent_ext/diagnosis/log/tools.py:41` | import 路径 `diagnosis.evaluation.report` → `utils.redaction`，一行 |
| `tests/utils/test_redaction.py`（新增） | 10 条用例：8 类规则用例 + 非字符串标量透传 + **re-export 同一性守卫**（`report.redact_sensitive is utils.redact_sensitive`） |

**脱敏规则零改动确认**：搬运块与原实现逐字一致（正则、替换串、docstring、注释全保留），
本卡只搬位置。`evaluation/` 内部模块（runner/executors/safety）**零改动**——
它们经 `report` 的 re-export 拿到的是同一函数对象（有测试钉死）。

## 验收结果

| 命令 | 结果 |
|---|---|
| 反向依赖扫描（任务卡命令） | **产品侧残留反向依赖：[]**（修前 `['...\\log\\tools.py']`） |
| `pytest tests/utils/test_redaction.py -q` | **10 passed** |
| `pytest tests/diagnosis/test_report_redaction.py -q` | **8 passed**（脱敏行为不变） |
| `pytest tests/diagnosis/log -q` | **28 passed** |
| `pytest tests/diagnosis -q` | **836 passed / 24 skipped**（与 main 基线一致，无回归） |
| `ruff check`（三个改动文件） | All checks passed |

## 取舍

- re-export 保留而不是全仓改 import：`evaluation/` 是待删代码，本卡 diff 最小化；
  删 re-export 会连带改 3 个文件，属 EVAL-P1b/P2 的活。
- `import re` 的移除严格服务于"re-export 化"这一步（ruff 必须绿），
  未触碰 report.py 其它任何函数。

## 没做的事 / 报告

- `evaluation/` 下未删任何文件（红线 3）。
- 除 `log/tools.py` 外未发现其它产品代码 import `diagnosis.evaluation`
  （红线 4 的扫描 = 本卡核心验收，结果为空）。
