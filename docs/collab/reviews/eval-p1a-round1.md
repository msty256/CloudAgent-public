# EVAL-P1a 审查结论 · 第一轮

> 审查人：DSH Lead · 2026-11-07 · 分支 `feat/eval-p1a-runrecord`（HEAD `e390684` + 未提交工作区）
> 任务卡：[`../tasks/eval-p1a-runrecord.md`](../tasks/eval-p1a-runrecord.md)
> 规格：[`../design/eval-p1a-runrecord-schema.md`](../design/eval-p1a-runrecord-schema.md)

## 结论：`PASS`（附 1 条必须回应的裁决 + 1 条建议）

质量高于预期。三条设计约束全部落地，**而且主动指出了我任务卡里的一处自相矛盾**（见 §2 疑问 1）。
我的三个疑问全部核实过，其中**疑问 2 是我 schema 写错了**，已裁决。

---

## 1. 验收闸门（我实跑，非采信 handoff）

| 闸门 | 结果 |
|---|---|
| `pytest tests/diagnosis/eval_support` | **65 passed**（record 39 / execute 18 / cli 8） |
| `pytest tests/diagnosis` 全量 | **926 passed / 24 skipped**（基线 861，+65，只增不减） |
| `ruff check cloudagent_ext tests` | **All checks passed** |
| 反向依赖（排除 sanctioned 桥） | **`[]`** |
| 反向依赖（含 eval_support） | `['...eval_support\\execute.py']` ← 见 §2 疑问 1 |

## 2. 三个规格疑问的裁决

### 疑问 1：验收 ③ 的扫描命令与约束 3 自相矛盾 → **你对了，我的错**

任务卡约束 3 明文允许 `eval_support → evaluation` 临时复用，但验收 ③ 的命令
只豁免 `evaluation/` 自身，**必然把 `execute.py` 扫出来**。

**裁决**：验收命令改为豁免 `eval_support/`（sanctioned 桥）。

```python
# 修正后的扫描（已作为 P1b/P2 的标准命令）
import glob, os
hits = []
for f in glob.glob('cloudagent_ext/**/*.py', recursive=True):
    if '__pycache__' in f:
        continue
    p = os.path.normpath(f)
    if p.startswith(os.path.normpath('cloudagent_ext/diagnosis/evaluation')):
        continue   # 评测包内部自引用，正常
    if p.startswith(os.path.normpath('cloudagent_ext/diagnosis/eval_support')):
        continue   # 任务卡约束 3 明文允许的临时桥，P2 还
    if 'diagnosis.evaluation' in open(f, encoding='utf-8', errors='ignore').read():
        hits.append(f)
print(hits)   # 期望 []
```

**你不改口径、同时贴两种结果的处置是对的**——比自行改验收命令更安全。

### 疑问 2：`empty` 的归属与 `scoring.categorize()` 不一致 → **我 schema 写错了**

我实测确认了这个不一致：

```
scoring.categorize(空输出)  →  'unfinished'
schema §4.1 第 3 步        →  'empty'
```

**裁决：以 `scoring.categorize()` 为准（空输出 = `unfinished`），我改 schema。**

理由：schema §4.1 那张判定表是我照着"执行层事实"想当然写的，
而现有 `_looks_unfinished()` 的 docstring 里已经论证过这个分类：

> 类别：`crashed` / `unfinished` / `invalid_output` / `parsed`
> ……"截断/撞顶 —— 模型**没拿到完整的作答机会**，是链路问题"

空输出正是"没拿到作答机会"，归 `unfinished` 是对的。`empty` 这个档是我多加的，
**应删除**——保留它只会让 P3 有两条互斥的判定路径。

**对你的影响**：`outcome.status` 六档改为五档：

```
ok | timeout | crashed | unfinished | invalid_output
```

`empty` 并入 `unfinished`。改动量：`OUTCOME_STATUSES` 去掉一项 + 判定表第 3 步改标 `unfinished`。
**这个改动由你来做**（见 §4 待办 1）。

### 疑问 3：`record_from_json` 容忍未知字段 → **保持容忍，你的判断正确**

你写的理由就是标准答案：

> request 是安全边界，record 是数据面。

- **`RunRequest` 必须严格**：它是防污染的第一道闸（防止答案被传进产品）。
- **`RunRecord` 应该宽容**：它是产品写给评测仓的数据。将来产品升了字段、
  评测仓还没跟上时，**读方拒收会造成"产品升级即评测瘫痪"**。
  "只增不改"的版本规则本意就是让加字段不破坏兼容。

**裁决：维持现状**。你推得对，设计文档没写清是我的疏漏——我已在 schema 文档里补记这条规则。

---

## 3. 三条设计约束的核查（我自己验，不只看用例名）

### 约束 1：`RunRequest` 拒绝 `ground_truth` ✅

我实测：

```python
request_from_json({..., "ground_truth": {...}})
→ RunRequestError: RunRequest 存在未知字段（协议层拒绝，防止把整份 case 连答案带进来）：ground_truth
```

文案直接说出理由，很好。

### 约束 2：`usage.available=false` → token 为 `None` ✅ **正向 + 反向都守住了**

正向（我实测）：
```python
usage = {"input_tokens": None, ..., "available": False}
→ 解析成功，input_tokens = None
```

**反向**（这才是我最想验的）：
```python
usage = {"input_tokens": 0, ..., "available": False}
→ RunRecordError: usage.available=false 时 token 字段必须为 null（不许写 0）
```

**拒绝了"没采到却写 0"这种冒充。** 这条守住了本卡最有价值的安全语义。

### 约束 3：`record.py` 零内部依赖 ✅（AST 级验证）

```
import 顶层模块: ['__future__', 'dataclasses', 'typing']
全是标准库: True
```

## 4. 红线核查

| 红线 | 结果 |
|---|---|
| 1. 不许把评分逻辑搬进 `eval_support` | ✅ 扫描 `match_terms/top1/top3/score_case` 等：仅 `execute.py:13` 一处**注释**在声明"出现即为越界"，无实际代码 |
| 2. 不许放宽 `dontAsk` | ✅ `_ALLOWED_PERMISSION_MODES = frozenset({"dontAsk"})`，白名单只有一个值 |
| 3. 不许改 `evaluation/` | ✅ `git status` 对 `evaluation/` 为空 |
| 4. `RunRequest` 结构上不许有 `ground_truth` | ✅ |
| 5. 真跑最多 1 个 case | ✅ 你选择跳过（额度红线），并在 handoff 声明——**同意** |

## 5. 我额外核的两件事

**`_wants_subagent_grade()` 副本会不会漂移？** 我对比了逻辑：

```
原实现: ['if grade_source == "subagent":', 'return True', 'if grade_source == "main":', 'return False', 'return dispatch_mode == "main"']
副本  : 完全相同
```

**当前一致**。你在 handoff 里已提示"P2 搬迁后应改为从唯一实现导入"——我把它写进了 P2 的待办。

**`status_provisional` 的设计**：只在 `ok` 时出现（缺席即"最终判定"）。
比恒出现该键的 diff 小，且语义清楚：**没有标记 = 这条已经定论**。认可。

---

## 6. 待办（合并前要做的，只有 1 件）

### 必须做：移除 `empty` 档

按 §2 疑问 2 的裁决，把 `outcome.status` 从六档改为五档：

```
ok | timeout | crashed | unfinished | invalid_output
```

具体改动：
1. `record.py`：`OUTCOME_STATUSES` 去掉 `"empty"`
2. `execute.py`：`_determine_status()` 第 3 步（`raw_output` 为空）→ 返回 `"unfinished"` 而不是 `"empty"`
3. `case_run_to_record()` 里那段 `if status == "ok": status, provisional = "empty", False` → 改 `"unfinished"`
4. 相关用例同步（含"六档"那组参数化 → 五档）
5. `docs/collab/design/eval-p1a-runrecord-schema.md` 我会同步改（**你不用动文档**）

### 建议做（不阻塞）：把副本标注为显式债务

`_wants_subagent_grade()` 已注明是副本，建议再加一句 `# TODO(P2): 改为从 evaluation.executors 导入`，
让 grep `TODO(P2)` 能一次找全所有待搬项。

---

## 7. 合并流程

改完 §6 那 1 件后，**先不要自己提交**，等我复验一次再合并。
因为这是删一个枚举值，会影响已写的用例——我要确认没有漏改的地方。
