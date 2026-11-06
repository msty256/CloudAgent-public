# EVAL-P1b 任务卡：评测仓骨架 + RunRecord 消费

| 项 | 值 |
|---|---|
| 工作包 | EVAL-P1b |
| 状态 | `ready` |
| 负责人 | ZCode |
| 仓库 | **评测仓（新建）** `C:\Users\Administrator\Desktop\cloudagent-eval` |
| 分支 | `main`（新仓，直接在主分支做） |
| 预估 | 1 天 |
| 依赖 | EVAL-P1a（需要产品侧 `eval-run` 子命令） |

> 设计依据：[`../design/eval-system-design.md`](../design/eval-system-design.md) §2、§11.2

## 目标

建一个**独立私有 git 仓**，能读取产品产出的 RunRecord 并跑通最小闭环：
**加载 request → 调产品 CLI → 收 RunRecord → 存档**。**不含评分**（P2 才做）。

## 仓库初始化（必须先做）

```powershell
# 1) 建目录与 git 仓
mkdir C:\Users\Administrator\Desktop\cloudagent-eval
cd C:\Users\Administrator\Desktop\cloudagent-eval
git init

# 2) ⚠️ 不要创建远程、不要 push（私有仓由项目所有者后续创建）
```

**目录结构**：

```
cloudagent-eval/
├── pyproject.toml
├── README.md
├── .gitignore
├── cloudagent_eval/
│   ├── __init__.py
│   ├── record.py            # RunRecord 的读取侧（与产品侧 schema 对齐，见下）
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── cloudagent_cli.py  # 调 `cloudagent eval-run` 子进程
│   ├── runner/
│   │   ├── __init__.py
│   │   └── execute.py       # 批量执行：requests → records
│   └── cli.py               # `cloudagent-eval` 命令行入口
├── datasets/                # P2 才填，本卡只建空目录 + .gitkeep
│   ├── golden/
│   └── holdout/
├── environments/            # P2 才填
├── runs/                    # 产物，gitignore
└── tests/
```

## 三个子任务

### T1b.1 `record.py` — RunRecord 读取侧

**不要重新发明 schema**。直接把 EVAL-P1a 的 `record.py` 复制过来（或做成同构）：

- 评测仓需要**独立**的 schema 定义（不能 import 产品仓——那会破坏独立性）
- 但字段必须与产品侧**逐字段一致**

**这是一处有意的重复**。理由：
- 若评测仓 import 产品的 schema 模块，评测仓就无法独立演进（R8 要求只读）
- 两边的契约由 **schema_version + 往返测试** 保证一致，不靠共享代码

**验收方式**：在产品仓导出一份示例 RunRecord（EVAL-P1a 的手动真跑产物），
放进评测仓 `tests/fixtures/`，断言评测仓的 `record_from_json` 能正确解析它。
**这是跨仓契约的守门测试**。

### T1b.2 `adapters/cloudagent_cli.py` — 子进程适配器

```python
def run_case(request: RunRequest, *, workdir: Path, timeout: float = 600) -> RunRecord:
    """调 `cloudagent eval-run --request ... --out ...` 并读回 RunRecord。"""
```

要点：
- 用 `subprocess.run(..., timeout=...)`，**捕获 stdout/stderr 但不解析 stdout**
  （只认 `--out` 写的文件，避免 stdout 格式变化影响契约）
- 子进程失败（非 0 退出）时：**仍尝试读 `--out` 文件**（按约束 3，失败也会写 record）
- 读不到文件时抛 `AdapterError`，带 stderr 尾部
- **不设 `shell=True`**
- 产品路径可配：`CLOUDAGENT_EVAL_SUBJECT_CMD` 环境变量（默认 `python -m cloudagent_ext.cli.main`）

### T1b.3 `runner/execute.py` + `cli.py` — 最小闭环

```bash
cloudagent-eval run --requests <dir-or-file> --out-dir runs/<id> [--holdout]
```

行为：
- 读 `RunRequest` 列表（JSON 或 JSONL）
- 逐个调适配器（**串行**，本卡不做并发——成本太高，并发容易失控）
- 每个 record 落盘 `runs/<run_id>/records/<case_id>.json`
- 写一个 `runs/<run_id>/manifest.json`，记录：
  `harness_version` / `subject_git_sha`（调 `git -C <product> rev-parse HEAD` 取）/
  `started_at` / `finished_at` / `request_count` / `record_count`
- **`--holdout` 标志本卡只做参数占位 + 显式警告**（"P5 才实现隔离"）

## 验收命令

```powershell
cd C:\Users\Administrator\Desktop\cloudagent-eval

# ① 包可安装、CLI 可跑
pip install -e .
cloudagent-eval --help

# ② 契约往返（用产品仓导出的真实 RunRecord 当 fixture）
python -m pytest tests -q

# ③ 端到端：1 个 mock request（适配器可注入 fake，不调真模型）
python -m pytest tests/test_adapter.py -q

# ④ 真跑 1 个 case（可选，烧额度；如果额度紧张可跳过并在 handoff 说明）
cloudagent-eval run --requests tests/fixtures/req-sql-001.json --out-dir runs/smoke
# 期望：runs/smoke/manifest.json + records/sql-001.json
```

## 完成定义

- [ ] `C:\Users\Administrator\Desktop\cloudagent-eval` 已 `git init`，**没有远程、没有 push**
- [ ] `pyproject.toml` 声明包名 `cloudagent-eval`、入口 `cloudagent-eval`
- [ ] `record.py` 能解析产品仓导出的真实 RunRecord（跨仓契约测试）
- [ ] 适配器用子进程调用产品 `eval-run`，**只读 `--out` 文件**，不解析 stdout
- [ ] `cloudagent-eval run` 能产出 `manifest.json` + 逐 case record
- [ ] `--holdout` 是显式标志且带警告（P5 才实现真正隔离）
- [ ] `runs/` 在 `.gitignore` 里
- [ ] handoff 写清：跨仓契约怎么保证一致（重复定义 + 往返测试）、P2 要补什么

## 红线

1. **不许 import 产品仓的 `cloudagent_ext`**。评测仓对产品只有"子进程调用"这一种关系。
   （P2 做历史 run 迁移时会读 JSON，不是 import 代码。）
2. **不许创建远程仓、不许 push**。
3. **不许把 `runs/` 提交进 git**。产物是本地数据。
4. 本卡**不做评分**。任何 scorer 都留到 P2。
