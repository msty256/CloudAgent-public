# P4 实施规格：评测链路缺陷收口

> 状态：`approved` · 设计：DSH Lead（2026-11-07）· 实现：ZCode
> 任务卡：[`../tasks/p4-eval-chain.md`](../tasks/p4-eval-chain.md)
> 独立工作包，不与 P1/P2/P3 有文件重叠，可立即开工

---

## 1. 问题陈述

`docs/baseline-attempt-2026-11-03.md` §5 与 §7 记录了两轮 live 尝试里发现的 8 个缺陷。
其中 6 个已修，**2 个明确标着"未修"**：

| # | 现象 | 原文 | 状态 |
|---|---|---|---|
| 7 | 输出截在半句话、无 json 块 | "**未修**：撞顶/截断应单独归类为 `unfinished`，不该混进 `invalid_output`" | 部分修（见下） |
| 5.1 | 子代理里 `Bash` 返回空字符串 | "trace 里子代理调了 `ls`，返回的是**空字符串**（`is_error=None`，内容空白），于是模型自己总结为 'Bash is unavailable'。`TOOL_SET_CODE_DIAGNOSIS` 里**是有 `Bash` 的**……要查执行环境（cwd / sandbox / 权限模式 `dontAsk`）" | **未修** |

### 我先核实了 #7 的现状（不是照抄文档）

`scoring.py:89-118` **已经**有 `_UNFINISHED_SENTINELS` 和 `_looks_unfinished()`，
`categorize()` 也确实把撞顶/空输出归到 `unfinished` 了。所以 #7 的**主诉求已实现**。

但它留了一个自己写明的口子：

> 试过"短且不含 `{` 就算截断"，结果把一个完整的短回答（"抱歉无法完成。"）也判成了没跑完
> …… **真正的截断仍然会落进 `invalid_output`，只是 error 说明里不带"未完成"标签。**

这就是 P4 要收的口：**"说了半句话"目前无法与"答完但格式不对"区分**，
两类混在一起统计，正是文档反复强调的"看起来像模型不行，其实是链路问题"。

### #5.1 我已核实是真实缺陷且可离线定位

`executors.py:92` + `:95-111` 把诊断链路的 `ToolContext.permission_context` 固定成
`dontAsk`。注释明说这是安全加固（防 Bash 写入）。
而 `dontAsk` 的语义是**need-ask 即拒**——在无交互环境里，
如果一个 Bash 调用落到"需要询问"分支，它会被**确定性拒绝**，
但返回的可能是**空内容 + 非 error**，模型于是当成"Bash 不可用"。

代码注释里有一句关键的话（`executors.py:100-102`）：

> 修复前该链路使用 `ToolContext` 默认的 `bypassPermissions`（Bash 检查全部短路）

也就是说 `dontAsk` 下 Bash 走的是**检查路径**。要确认到底哪一步产出空串，
需要离线复现：用一个已知只读命令（`ls` / `pwd` / `echo ok`）在
`build_diagnosis_tool_context()` 下直接调 `Bash` 工具，看返回什么。

**这一步完全离线可做，不需要模型。**

## 2. 要做什么（三个 T）

### T4.1 复现并定位「Bash 返回空」

新增 `tests/diagnosis/test_eval_bash_availability.py`：

```python
def test_bash_readonly_command_returns_content_under_eval_context():
    ctx = build_diagnosis_tool_context()          # dontAsk
    result = BashTool.call({"command": "echo cloudagent-probe"}, ctx)
    assert not result.is_error
    assert "cloudagent-probe" in str(result.output)   # ← 现在大概率失败
```

分三种上下文参数化，把"是谁导致的空"定位到具体一层：

1. `build_diagnosis_tool_context()`（`dontAsk`）→ 期望能跑；跑不了就是本案缺陷；
2. `ToolContext(workspace_root=...)`（默认权限）→ 作为对照，必须能跑；
3. `dontAsk` 下一条**明确需要询问**的命令（如 `rm -rf /tmp/x`）→ 期望**被拒且 `is_error=True`**。

第 3 条是**安全红线的守门**：修 #5.1 时绝不允许把 `dontAsk` 放宽成
`bypassPermissions`——那会把安全加固整个废掉。**这是本工作包最重要的约束。**

修复方向（按优先级，实现时先做 1，验证够不够）：

1. **让拒绝变成显式错误**：`dontAsk` 下被拒的 Bash 返回
   `is_error=True` + 明确文案（"permission denied by eval sandbox: <reason>"）。
   这样即使代码域跑不了命令，模型也不会得出"工具不存在"的错误结论，
   `unfinished` / `invalid_output` 的归因也不再被骗。
2. **给评测链路一份"只读可执行"白名单**：在 `dontAsk` 模式下放行
   可证明只读的命令（`ls` / `pwd` / `git status` / `grep` / `cat` 之类）。
   注意：`executors.py:96-99` 的注释说"可证明只读且限域的命令放行"——
   **实现时要查证这句话现在是否真的成立**。如果不成立，说明注释与代码不符，
   要在 handoff 里单列。
3. **不要**改成 `bypassPermissions`。这是红线。

### T4.2 截断判定：从"看长度"改成"看结构"

`_looks_unfinished()` 现在只认 sentinel（撞顶信标）。新增**结构化信号**，
全部是"确定性的"，不猜：

| 信号 | 判定 |
|---|---|
| 文本含 ` ```json ` 开块但**没有闭块** | 截断 |
| 文本含 ` ```json ` 开块、有闭块，但闭块后 `json.loads` 失败且**错误位置在末尾** | 截断 |
| 文本以逗号 / 冒号 / 开括号（`{` `[`）结尾（去掉尾部空白后） | 截断 |
| 文本长度 < 20 且不含任何 JSON 结构字符 | **不判**（保持现状，避免误伤"抱歉无法完成。"） |

**判定顺序**必须写在 docstring 里，且**新增的信号只能提高召回、不能降低精度**：
每一条新信号都要配一条"完整回答不能被我误判"的反向用例。

改完后：
- `unfinished` 与 `invalid_output` 的**分界线**要写进 `scoring.py` 的模块 docstring；
- `runner.py:878` 的输出表已经列了 `unfinished`，确认它对 `_compare_runs` 的对照表也生效
  （现在对照表只列了一部分类别，**如果漏了 `unfinished` 就是本 T 的缺陷**）。

### T4.3 顺手清掉 3 处 F821（本工作包唯一允许的"顺带"改动）

这三处是 `ruff check` 红的原因，且都因为 `from __future__ import annotations` 而无害：

| 位置 | 修法 |
|---|---|
| `cloudagent_ext/agent/registry.py:159` | `from typing import TYPE_CHECKING, Any, Callable` |
| `tests/diagnosis/test_session_wiring.py:685`（2 处） | 加 `from pathlib import Path`，注解改 `Path` |

> 为什么放在 P4：它是评测链路相关测试文件的直接修补，改动 2 行，
> 且 P1/P2/P3 都不碰这两个文件，不会冲突。**除此之外不许夹带任何无关改动。**

## 3. 验收标准

```powershell
# ① Bash 可用性（新）
python -m pytest tests/diagnosis/test_eval_bash_availability.py -q -rs
# 期望：3 passed（第 3 条是"拒绝必须是显式错误"的安全守门）

# ② 截断判定（改 scoring.py 后）
python -m pytest tests/diagnosis/test_eval_metrics.py -q
python -m pytest tests/diagnosis/test_evaluation_runner.py -q

# ③ ruff 清零
python -m ruff check cloudagent_ext tests
# 期望：All checks passed!（现在是 3 errors）

# ④ 全量诊断域
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider

# ⑤ 离线跑一次，确认报告结构没被改坏
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync
```

## 4. 明确不做

| 不做 | 理由 |
|---|---|
| 放宽 `dontAsk` 成 `bypassPermissions` | **安全红线**。见 T4.1 |
| 用"输出长度"判截断 | `scoring.py:114-117` 已经试过并推翻了，理由写得很清楚 |
| 修 #7 的另一半（`main` 模式子代理结果无法解析） | 需要 live 复现才能确认；且 `_last_subagent_payload` 已经存在，可能已修。**标为观察项，不写代码** |
| 动 provider / 端点 / 额度相关 | 见 `docs/needs-quota.md` |
| 给 `unfinished` 造新的指标口径 | 那是度量设计，属 P2 之后的独立工作包 |

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 修 Bash 时可执行命令范围放开过度 | 只放开"确定只读"命令；`rm`/`mv`/`dd`/重定向写入必须在拒绝清单里，且有用例守 |
| 新增截断信号把完整短回答误判成 unfinished | 每条信号配反向用例；第 4 条信号明确"短回答不判" |
| 有人误以为 P4 修完就能跑 live | **不能**。P4 只修链路缺陷，额度约束不变（见基线文档 §6） |
