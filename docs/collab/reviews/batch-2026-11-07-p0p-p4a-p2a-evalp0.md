# 批次审查结论（2026-11-07 · P0'/P4a/P2a/EVAL-P0）

> 审查人：DSH Lead
> 范围：P0'（已合 main）+ P4a / P2a / EVAL-P0（三分支待合）
> 方法：**逐条实跑复验**，不看声明；对守卫用例做了**破坏性自验**

## 总结论

| 工作包 | 分支 | 结论 |
|---|---|---|
| **P0'** | 已合 main（`2fffe88`） | ✅ **PASS 已生效**（数据库中验） |
| **P4a** | `feat/p4a-f821` | ✅ **PASS** |
| **P2a** | `feat/p2a-switch-registry` | ✅ **PASS**（守卫经破坏性自验） |
| **EVAL-P0** | `feat/eval-p0-redaction` | ✅ **PASS**（脱敏逐字一致已验） |

四个包质量都在水准之上，**无一条打回**。下面是我实际做了什么。

---

## 1. P0'（已在 main）

**我没有只读 handoff，而是直接查了数据库：**

```sql
-- 上游 cloudagent_sim
select * from pg_default_acl;                   -- → 0 行 ✅
select relname, relacl from pg_class where ...; -- → 4 张表 relacl 未变 ✅
```

只读角色行为验证：

| 表 | 行数 | 状态 |
|---|---|---|
| orders | 50000 | ✅ 可读 |
| customers | 2000 | ✅ 可读 |
| devices | 50 | ✅ 可读 |

**零误伤确认**：`tenants`/`devices` 的表级授权保留了（这正是我在任务卡里强调"不能收"的部分）。

**ZCode 主动报告的下游库残留，我已核实属实**：

```
cloudagent_sim_downstream: postgres | public | r   ← 同样的残留还在
```

它按红线 2 没有动，只报告。**判断正确**。→ 转为 P0''（见下）。

---

## 2. P4a — PASS

`git diff` 就是两行，无夹带：

```diff
-from typing import TYPE_CHECKING, Callable
+from typing import TYPE_CHECKING, Any, Callable
```

```diff
 import asyncio
 import json
+import pathlib
 import threading
```

**验收**：
- `ruff check cloudagent_ext tests` → **All checks passed!**（修前 3 errors）
- `pytest tests/diagnosis tests/agent` → **1181 passed / 27 skipped**

这正是"小债不该被大工程阻塞"的样本：15 分钟，ruff 从红变绿。

---

## 3. P2a — PASS（我做了破坏性自验）

这是本批次风险最高的包（改了 3 个产品文件的读取逻辑 + 新增 25 条守卫）。
规格红线要求"改坏读取逻辑，守卫必须红"——**ZCode 在 handoff 里自述验过，我自己又验了一遍**：

### 自验 ①：把 `gap_injection_enabled()` 改成恒 `return True`

```
FAILED test_off_keeps_prompt_untouched[false]
FAILED test_off_keeps_prompt_untouched[0]
FAILED test_off_keeps_prompt_untouched[no]
FAILED test_off_keeps_prompt_untouched[off]
4 failed, 21 passed
```

### 自验 ②：把 `current()` 的 bool 分支改成恒 `True`

```
FAILED TestContextReduceBehavior::test_off_false_disables_reduction
FAILED TestEvidenceInvalidationBehavior::test_off_zero_keeps_resolved
2 failed, 23 passed
```

**两次都红，且红的正是对应的守卫。** → 守卫是真的，不是假守卫。

还原后 `25 passed`，`git status` clean（我确认了还原干净）。

### 真 bug 修复验证（我独立跑，不用它的数字）

```
CLOUDAGENT_GAP_INJECTION='false' -> False    ← 修前 True
CLOUDAGENT_GAP_INJECTION='0'     -> False
CLOUDAGENT_GAP_INJECTION='no'    -> False
CLOUDAGENT_GAP_INJECTION='off'   -> False
CLOUDAGENT_GAP_INJECTION='FALSE' -> False    ← 大小写也不误判
CLOUDAGENT_GAP_INJECTION='Maybe' -> True     ← 认不出 → 回退默认，不猜
CLOUDAGENT_GAP_INJECTION=''      -> True     ← 空值 → 默认
```

**语义变更确认为修 bug**：`=false/0/no` 从"无效"变"关闭"。做出闭环。

### 我赞同一个实现取舍

`current()` 对 mode 开关的非法值**静默**回退，告警留在读取点
（`domain_gate_mode` / `assessor_strategy`）。理由：告警要带模块 logger 上下文，
放登记表里会让 `switches.py` 依赖调用方日志配置。**这个判断是对的**，
规格只要求"读取点从登记表取 env/合法值"。

### `goal_stop_strategy` 的诚实边界也守住了

用例类名标 `[strategy-layer-only]`，handoff 明写"核查器确实没被调用需要 live"。
**没有假装守住执行层**——这正是规格红线 4 要求的。

**验收**：`tests/diagnosis` **861 passed / 24 skipped**（836 + 25，只增不减）。

---

## 4. EVAL-P0 — PASS（脱敏逐字一致，我做了 git 级比对）

这是"还技术债"的包，最怕的是**借搬家之机改脱敏规则**。我用 git 取出 main 上的旧实现逐字对比：

| 项目 | 结果 |
|---|---|
| `_DSN_PATTERN` | **IDENTICAL** |
| `_PASSWORD_ASSIGN` | **IDENTICAL** |
| `_KEY_PREFIX` | **IDENTICAL** |
| `_PHONE_PATTERN` | **IDENTICAL** |
| `_EMAIL_PATTERN` | **IDENTICAL** |
| `_redact_dsn` | **IDENTICAL** |
| `redact_sensitive` | **IDENTICAL** |
| `redact_payload` | **IDENTICAL** |

**一个字都没改，是纯搬家。**

### 核心验收：反向依赖清零

```
产品侧残留反向依赖： []      ← 修前 ['cloudagent_ext\\diagnosis\\log\\tools.py']
```

（注意：这个扫描命令我在任务卡里改过一次，因为最初版本会把 `evaluation/` 内部
4 条自引用误报成"反向依赖"。实际跑出来 `[]`，说明排除逻辑正确。）

### 向后兼容验证

```python
from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive
from cloudagent_ext.utils.redaction import redact_sensitive as r2
redact_sensitive is r2  →  True      ← 同一函数对象
```

re-export 保住了，`evaluation/` 下 3 个内部模块零改动。

**验收**：`tests/diagnosis + tests/utils` → **846 passed / 24 skipped**；
`test_redaction.py` 10 passed；`test_report_redaction.py` 8 passed。

> 注：该分支上 `ruff` 仍报 3 errors——那是 **P4a 尚未合入**导致的，
> 不是 EVAL-P0 的问题。P4a 分支上 `ruff` 已 All checks passed。

---

## 5. 合并顺序建议

三个分支互不冲突（P4a 改 `registry.py` + `test_session_wiring.py`；
P2a 改 `switches.py`/`agent.py`/`assessor.py`/`runtime_session.py`；
EVAL-P0 改 `report.py`/`log/tools.py`/新增 `utils/redaction.py`）。

```
git checkout main
git merge --no-ff feat/p4a-f821            # 先合，ruff 立刻清零
git merge --no-ff feat/eval-p0-redaction   # 再合，反向依赖清零
git merge --no-ff feat/p2a-switch-registry # 最后（改动面最大）
```

**合并后 `ruff check` 应为 All checks passed**，这是三包叠加的联合验收。

---

## 6. 新发现：下游库有同样残留 → P0''

ZCode 按红线 2 只报告不动，判断正确。我实测确认：

```
cloudagent_sim_downstream: pg_default_acl = [('postgres','public','r')]   ← 还在
```

**处置**：出 P0'' 任务卡（与 P0' 完全同构，只换库名 + 需确认下游 4 张表 relacl 不变）。
不阻塞合并，可与下一批并行。

---

## 7. 四个包的共同优点（值得保持）

1. **handoff 都写了"没做的事"**，且不是敷衍——P0' 报告下游残留、P2a 报告 strategy 层边界；
2. **验收表贴的是命令 + 结果**，不是"已通过"；
3. **改动都守住了任务卡红线**：P4a 没夹带、P2a 没动默认值、EVAL-P0 没改规则。

反过来说，我这批任务卡也有一处需要改进：**P0' 的任务卡没有预先写"下游库可能也有"**，
是 ZCode 自己发现的。下次写"清某个环境状态"的任务卡，应默认加一条
"检查同类环境是否需要同样处理"。
