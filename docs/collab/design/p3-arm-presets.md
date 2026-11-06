# P3 实施规格：多臂预设 —— `variant` 只是预设，开关独立

> 状态：`approved` · 设计：DSH Lead（2026-11-07）· 实现：ZCode
> 任务卡：[`../tasks/p3-arm-presets.md`](../tasks/p3-arm-presets.md)
> 前置：**P2 必须先合并**（否则新臂一样"关了但没关"）

---

## 1. 问题陈述

`docs/needs-quota.md` §6 第 1 条：

> 阶段 5 的多臂预设 | `variant` 目前只有 `gaps-on`/`gaps-off`；要做成"开关独立 + variant 只是预设"。
> 开关本体（阶段 3/4 两个）已经就绪

**这条现在部分过时了。** 我读了 `runner.py:140-170`，实际已经有 **8 个 preset**：

```
gaps-on / gaps-off / baseline / arm:domain / arm:state / arm:inval / arm:reduce / kb-on / kb-off
```

也就是说"多臂预设"这件事**大体已经做了**。真正缺的是三件事：

### 缺口 1：不能"独立指定开关"，只能选预设

现在只能 `--variant arm:reduce`。如果要做
"**同时关掉压缩和失效传播**"这种组合（阶段 5 提案里的 4 臂设计需要），
就得新增第 9、10… 个 preset，**组合数会爆炸**（2^5 = 32 个预设）。

而且更糟的是：**新增 preset 时很容易忘记它是相对 baseline 的**，
`arm:inval` 的注释已经踩过这个坑：

> `arm:inval` 必须同时开 `hybrid`：失效传播要求"回退后再次 resolved 须过核查"，
> 而 `agent_report` 档下核查根本不跑——单开 invalidation 会得到一个"永远不收敛"的臂。

**这是设计层面的信号**：preset 里藏着"开关之间的依赖关系"，而依赖关系目前只写在注释里。

### 缺口 2：预设的正确性没有守门

现在没有任何东西验证：
- `arm:reduce` 相对 `baseline` **只改了一个**开关（"严格单变量"这个宣称是注释里的，不是测试里的）；
- `arm:inval` 确实同时改了 2 个（且第三个是**必要依赖**，不是第二变量）。

### 缺口 3：run 报告里分不清"这臂的差异归因于哪个开关"

`run_payload["arm_env"]` 有完整环境快照，但没有**推导**：读者要自己 diff 两个 dict
才知道"这一臂到底动了什么"。对照实验报告的价值一半在这里。

## 2. 要做什么（三个 T）

### T3.1 让 `--variant` 支持"预设 + 显式覆盖"

在 `runner.py` 里新增 CLI 参数（**不动现有 `--variant` 语义**）：

```
--set KEY=VALUE     # 可重复；在 --variant 展开后覆盖单个开关
--arm-from NAME     # 以哪个预设为基线（默认 baseline），配合 --set 使用
```

语义定义（写进 `--help` 与 docstring）：

1. `--variant X` = `--arm-from`（若给了）展开后，再应用 `--variant X` 预设；
2. `--set K=V` 在最后应用，**覆盖**任何预设；
3. 展开结果存进 `run_payload["arm_env"]`（已存在，保持）；
4. **新增** `run_payload["arm_derivation"]`：相对基线**逐项列出差异**：

```json
{
  "base": "baseline",
  "overrides": {"CLOUDAGENT_CONTEXT_REDUCE": "on"},
  "changed": {
    "CLOUDAGENT_CONTEXT_REDUCE": {"from": "off", "to": "on"}
  },
  "single_variable": true,
  "declared_dependencies": []
}
```

`single_variable` 是**本 T 的核心产出**：一个布尔值，回答"这一臂相对基线只动了一个开关吗"。
它让"严格单变量"从注释里的一句话变成**报告里的一个字段**。

### T3.2 把"开关依赖"变成数据

P2 已经建了 `SWITCHES` 登记表。在预设里声明依赖：

```python
# arm:inval 的正确性依据不再是注释，而是这条声明
_ARM_DEPENDENCIES: dict[str, tuple[tuple[str, str], ...]] = {
    # (被依赖开关, 为什么必须这样)
    "CLOUDAGENT_EVIDENCE_INVALIDATION": (
        ("CLOUDAGENT_GOAL_STOP_STRATEGY", "hybrid"),
    ),
}
```

展开预设后**校验**：如果某开关被打开但它声明的依赖不满足，
`base` 臂直接 `EvaluationError`，理由指出具体是哪条依赖没满足。

> 为什么放在 T3 而不是 P2：P2 的登记表回答"开关关了真的关了吗"，
> T3 回答"开关之间谁依赖谁"。**两件事分开比塞进一个 dict 好维护。**

### T3.3 单变量守门

新增 `tests/diagnosis/test_arm_presets.py`：

1. **每个 `arm:*` 预设相对 `baseline` 必须 `single_variable=True`**，
   例外只有 `arm:inval`（它声明了依赖），且例外必须在测试里**逐字列出**（锁死）。
2. `kb-on` / `kb-off` 必须**只差一个开关**且互为镜像。
3. `gaps-on` 必须等于"不改任何开关"（= 生产默认）——用空 dict 断言。
4. 给了 `--set` 的组合，`arm_derivation.changed` 必须准确。
5. 依赖未满足时**必须报错**，且报错文案里点名是哪个开关。

同时把 `test_ab_experiment.py` / `test_evaluation_runner.py` 里对
`variant` / `arm_env` 的现有断言保持通过（**不许改它们的期望值**，只能新增）。

## 3. 验收标准

```powershell
# ① 新守门
python -m pytest tests/diagnosis/test_arm_presets.py -q

# ② 原有对照实验用例不许动期望值
python -m pytest tests/diagnosis/test_ab_experiment.py tests/diagnosis/test_evaluation_runner.py -q

# ③ 离线跑一个预设，确认 arm_derivation 落盘
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant arm:reduce
# 期望：run json 里 arm_derivation.single_variable == true

# ④ 显式覆盖（离线，不烧额度）
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant baseline --set CLOUDAGENT_CONTEXT_REDUCE=on

# ⑤ 依赖校验
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --arm-from baseline --set CLOUDAGENT_EVIDENCE_INVALIDATION=on
# 期望：EvaluationError，文案指出 GOAL_STOP_STRATEGY 依赖未满足

# ⑥ 全量
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
```

## 4. 明确不做

| 不做 | 理由 |
|---|---|
| 删掉任何现有 preset | 历史 run 的 `variant` 字段要还能解析 |
| 改 `_BASELINE_ENV` 取值 | 会作废历史实验 |
| 跑任何 live 臂 | 额度（见 `docs/needs-quota.md`）；本包全部离线验收 |
| 自动生成 32 个组合 preset | 那正是 `--set` 要避免的 |
| 改 `_compare_runs` 的表格口径 | 属于度量设计，独立工作包 |

## 5. 风险

| 风险 | 缓解 |
|---|---|
| `--set` 让人配出语义上荒谬的臂（如同时 `gaps-off` + `arm:inval`） | 依赖校验只兜"必要依赖"；荒谬组合无法穷举，落盘 `arm_derivation` 让人事后可审 |
| `single_variable` 定义成"diff 数量 == 1"，`arm:inval` 会被判 false | 所以例外要**显式声明**（T3.2 的依赖表），不是靠放宽判定 |
| 新增 CLI 参数与现有 `--variant` 组合产生歧义 | 语义按 T3.1 的三条定义写死，且必须有用例覆盖组合顺序 |
