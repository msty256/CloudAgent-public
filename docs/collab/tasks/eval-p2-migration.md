# EVAL-P2 任务卡：等价迁移（历史 run + 现有 38 题）

| 项 | 值 |
|---|---|
| 工作包 | EVAL-P2 |
| 状态 | `ready`（但必须在 P1a/P1b 之后） |
| 负责人 | ZCode |
| 仓库 | **两个仓都动**：评测仓（主体）+ 产品仓（删除 `evaluation/`） |
| 分支 | 评测仓 `main` / 产品仓 `feat/eval-p2-remove-eval` |
| 预估 | 2 天 |
| 依赖 | EVAL-P1a + EVAL-P1b |

> 设计依据：[`../design/eval-system-design.md`](../design/eval-system-design.md) §5.2、§8 P2、§9

## 目标（这是整个迁移的**验收锚点**）

把评测逻辑搬到评测仓，并**证明搬迁没改变任何判断**：

> 用新评分器重算历史记录，**逐题结果必须与旧评分器一致**（strict 口径）。
> 不一致的必须逐条解释，不许含糊过去。

这条等价性是后面所有改进（P3 修口径、P4 统计、P5 生成器）的**信任基础**。
如果跳过这步直接改口径，将来分数变化就分不清是"改进了"还是"搬坏了"。

## 四个子任务

### T2.1 迁移评分器（评测仓）

从产品仓 `cloudagent_ext/diagnosis/evaluation/` 搬到评测仓 `cloudagent_eval/scorers/`：

| 源文件 | 目标 | 改动 |
|---|---|---|
| `scoring.py`（29 KB） | `scorers/legacy.py` | **逻辑一字不改**，只改 import（`diagnosis.protocol` → 评测仓自己的 protocol 定义） |
| `safety.py`（9 KB） | `scorers/safety.py` | 同上 |
| `report.py` 的报告部分 | `report/markdown.py` | 脱敏已由 EVAL-P0 迁走，这里只用不定义 |

**关键难点**：`scoring.py` 依赖 `cloudagent_ext.diagnosis.protocol.parse_diagnosis_result`
和 `text_match._contains_all`。评测仓不能 import 产品。两条路：

- **(a) 复制一份协议定义到评测仓**（推荐）：`cloudagent_eval/protocol.py`，
  含 `parse_diagnosis_result` + `DiagnosisResult` 的最小只读镜像。
  与产品侧的一致性用**往返测试**保证（拿产品的真实输出当 fixture）。
- (b) 产品的输出已经在 RunRecord.`outcome.raw_output` 里，评测仓自己解析。
  这也是 (a) 的一部分——本来就要自己解析。

**选 (a)**。理由：评测仓必须能独立解析，否则"独立"是假的。

### T2.2 迁移数据集 + 环境（评测仓拥有）

按**已定决策 D-ENV**：环境定义归评测仓。

| 从产品仓 | 到评测仓 | 说明 |
|---|---|---|
| `cloudagent_ext/diagnosis/cases/**`（39 JSON，91 KB） | `datasets/golden/` | 按域分子目录，保持原文件名 |
| `tests/fixtures/sql/seed.sql` | `environments/sql/seed.sql` | 原样搬 |
| `cloudagent_ext/diagnosis/log/fixtures/sim_logs.py` | `environments/log/sim_logs.py` | 原样搬（去掉对产品的依赖，若没有依赖则直接搬） |
| `cloudagent_ext/diagnosis/sync/fixtures/sim_sync_logs.py` | `environments/sync/` | 同上 |
| `tests/diagnosis/test_sql_seed_contract.py` | `tests/test_seed_contract.py` | 改路径 |

**产品仓保留什么**：产品自己的单测需要的最小 fixture。
如果某 fixture 两边都要（如 `sim_logs.py`），**评测仓拥有权威版本，产品仓保留一份用于单测**。
这处重复是设计上接受的代价（见 §9.2 的理由：产品改 fixture 不该静默改变 benchmark）。

### T2.3 历史 run 迁移 + 等价性验证（**本卡的核心**）

产品仓 `eval/runs/` 有 16 次历史 run（`run.json` + `cases/*.json`）。
写一个一次性转换器，把它们转成 RunRecord：

```
eval/runs/<run_id>/run.json + cases/*.json  →  cloudagent-eval/runs/<run_id>/records/*.json
```

**注意**：历史 run 的产物字段与 RunRecord 不完全一致（历史产物是评分后的结果，
RunRecord 是执行记录）。转换时要：
- 能从历史产物恢复的字段就填（`raw_output` / `meta` / `calls` / `events`）
- 恢复不了的（如 `subject.git_sha` 历史没记）填 `"unknown"` 并**在报告里标"不完整"**
- **不许编造**任何字段

然后：

```
1. 用新评分器（从旧 scoring.py 搬来的）重算这些 RunRecord
2. 与历史 run.json 里的 metrics 逐题对比
3. 产出差异报告：
   - 完全一致：✅
   - 不一致：逐条列 case_id / 旧值 / 新值 / 原因分析
```

**硬验收**：strict 口径下**逐题一致**。
不一致只有两种可接受解释：
- 历史产物的字段缺失导致无法重算（必须在报告里列清）
- 旧评分器有 bug（那就修，但要在报告里说明"这是修复不是回归"）

### T2.4 产品仓删除评测代码

**只在 T2.1–T2.3 全部通过后才做**。

删除清单（实测 219.8 KB）：
```
cloudagent_ext/diagnosis/evaluation/     （7 文件，133.9 KB）
cloudagent_ext/diagnosis/cases/          （39 JSON，91.1 KB）
cloudagent_ext/diagnosis/case_library.py
```

连带要处理的测试（迁走或删）：
```
tests/diagnosis/test_case_library.py
tests/diagnosis/test_case_meta.py
tests/diagnosis/test_evaluation_runner.py
tests/diagnosis/test_eval_metrics.py
tests/diagnosis/test_ab_experiment.py
tests/diagnosis/test_sql_seed_contract.py
tests/diagnosis/test_code_log_cases.py
tests/diagnosis/test_sync_cases.py
tests/diagnosis/test_multi_domain_evaluation.py
```

**注意**：`tests/diagnosis/test_cross_domain_integration.py` 与 `test_gap_orchestration.py`
**用到** `case_library` 但测的是**产品行为**。这两个要改成用内联 fixture，
**不能直接删**（它们守的是产品逻辑，不是评测）。

## 验收命令

```powershell
# === 评测仓 ===
cd C:\Users\Administrator\Desktop\cloudagent-eval

# ① 评分器单测（从产品仓搬来的用例要一起搬，保证行为一致）
python -m pytest tests/scorers -q

# ② 等价性验证（本卡核心）
python -m cloudagent_eval.tools.equivalence_check --runs-dir runs/migrated
# 期望：输出逐题对比表，strict 口径 100% 一致（或差异全部有解释）

# ③ 数据集完整性
python -m cloudagent_eval.tools.dataset_audit
# 期望：38 题全部可加载、28 static / 4 runtime / 6 external 与迁移前一致

# === 产品仓 ===
cd C:\Users\Administrator\Desktop\CloudAgent-public

# ④ 评测代码已删除
python -c "import pathlib; print('evaluation exists:', pathlib.Path('cloudagent_ext/diagnosis/evaluation').exists())"
# 期望 False

# ⑤ 产品测试无回归（基线 836 passed / 24 skipped，删除评测测试后会减少）
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
python -m pytest tests/context tests/tool_system -q --no-header -p no:cacheprovider

# ⑥ 产品仍能正常跑诊断（不是只剩空壳）
python -m cloudagent_ext.cli.main eval-run --request /tmp/req.json --out /tmp/rec.json

# ⑦ 反向依赖与残留引用清零
python -c "
import glob
hits=[f for f in glob.glob('cloudagent_ext/**/*.py',recursive=True) if 'diagnosis.evaluation' in open(f,encoding='utf-8',errors='ignore').read() or 'case_library' in open(f,encoding='utf-8',errors='ignore').read()]
print('残留引用：',hits)"   # 期望 []

# ⑧ lint
python -m ruff check cloudagent_ext tests
```

## 完成定义

- [ ] 评测仓能独立解析产品协议（不 import 产品代码）
- [ ] 38 题全部迁移，`verification` 分布与迁移前一致（28/4/6）
- [ ] 环境定义（seed.sql / sim fixtures）迁入评测仓 `environments/`
- [ ] 16 次历史 run 转成 RunRecord，缺失字段标 `unknown`，**不编造**
- [ ] **等价性验证：strict 口径逐题一致**（或差异逐条解释）
- [ ] 产品仓 `evaluation/` / `cases/` / `case_library.py` 已删除
- [ ] 产品仓测试无回归（删掉的评测测试不计）；**`test_cross_domain_integration.py` 与 `test_gap_orchestration.py` 必须改成内联 fixture 后全绿**
- [ ] 产品仍能跑 `eval-run`（迁移没把产品打成空壳）
- [ ] `ruff check` 全绿

## 红线

1. **等价性没验通过之前，不许删产品仓的 `evaluation/`**。顺序不能反。
2. **不许改评分逻辑**。本卡是搬家。想改口径 → P3。
3. **不许编造历史 run 的缺失字段**。
4. **`test_cross_domain_integration.py` / `test_gap_orchestration.py` 不许直接删**——
   它们测的是产品行为，要改 fixture 保留。
5. 迁移完成后**产品仓不许还能 import `case_library`**（那说明只搬了一半）。
