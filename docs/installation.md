# 安装与配置

两种安装方式，先选一种：

| 方式 | 适合谁 | 装到哪 | 升级 |
|---|---|---|---|
| **A. 一键脚本**（推荐） | 只想用，不改代码 | `~/.cloudagent/cloudagent`，并把 `cloudagent` 注册到 PATH | `.\install.ps1 update` / `./install.sh update` |
| **B. 源码安装** | 要改代码、跑测试 | 你 clone 的目录（可编辑安装） | `git pull` |

两种方式装出来的命令都是 `cloudagent`，后续配置完全一样。

---

## A. 一键脚本

### Windows

```powershell
git clone https://github.com/msty256/CloudAgent-public.git
cd CloudAgent-public

# 脚本未签名，需要在当前会话放开执行策略
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install
```

如果你在 PowerShell 里直接 `.\install.ps1 install` 报「未对文件进行数字签名」，
就是执行策略问题，用上面那行（只对本次调用生效，不改系统设置）。

### macOS / Linux

```bash
git clone https://github.com/msty256/CloudAgent-public.git
cd CloudAgent-public
./install.sh install
```

### 脚本做了什么

安装器基于 **uv**（未安装时会自动通过 winget 或 GitHub 发布包安装），锁文件固定版本：

1. 部署源码到 `~/.cloudagent/cloudagent`（`-InstallDir` 可改）
2. `uv venv --python 3.11 .venv` + `uv sync --extra all`（按 `uv.lock` 固定依赖）
3. 在 `~/.local/bin/` 生成 `cloudagent` 命令，并加入用户 PATH（卸载时只移除自己加的条目）
4. 配置目录 `~/.cloudagent`（`-ConfigDir` 可改）

从 clone 目录里运行时是**本地源码模式**：直接部署当前 checkout，不再去上游拉代码。

不确定会发生什么？先干跑一遍：

```powershell
.\install.ps1 install -DryRun
```

它会打印每一步要执行的命令，不改任何文件。

### 常用子命令

```powershell
# Windows
.\install.ps1 status      # 装在哪、哪个版本、PATH 是否就绪
.\install.ps1 doctor      # 依赖与环境的详细体检
.\install.ps1 verify      # 校验安装完整性
.\install.ps1 update      # 升级到最新
.\install.ps1 uninstall   # 卸载（含移除自己加的 PATH 条目）
.\install.ps1 help        # 全部参数
```

```bash
# macOS / Linux
./install.sh status
./install.sh doctor
./install.sh verify
./install.sh update
./install.sh uninstall
./install.sh help
```

（`install` 是默认子命令，省略即执行安装。）

常用参数（两种脚本写法不同，别混用）：

| 用途 | Windows | macOS / Linux |
|---|---|---|
| 改安装目录 | `-InstallDir <path>` | `--install-dir <path>` |
| 改配置目录 | `-ConfigDir <path>` | `--config-dir <path>` |
| 只打印不执行 | `-DryRun` | `--dry-run` |
| 跳过确认 | `-Yes` | `--yes` |
| 不用虚拟环境 | `-NoVenv` | `--no-venv` |

### 装完先自检

```powershell
.\install.ps1 status      # 装在哪个目录、哪个版本、PATH 是否就绪
cloudagent doctor         # 环境与版本体检
cloudagent --version      # 版本号
```

> - `status` 是**安装脚本**的子命令，不是 `cloudagent` 的子命令。
> - **不要用 `cloudagent diag` 当自检**：`diag` 是冻结/卡死诊断报告，需要跟子命令
>   （`freeze-report` / `viewer` / `status`），与环境体检无关。

---

## B. 源码安装（开发用）

```bash
git clone https://github.com/msty256/CloudAgent-public.git
cd CloudAgent-public

python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[db,dev]"    # 开发额外装 dev（pytest 等）
```

`-e` 是编辑模式：改代码立即生效，不用重装。

跑测试确认环境正常：

```bash
pytest tests/diagnosis -q              # 诊断域全量
pytest tests/diagnosis/security -q     # 只读对抗套件
```

---

## 环境要求

| 项 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.11 | 一键脚本会用 uv 拉取 3.11；源码安装用你本机的 3.11+ |
| Git | 任意 | **必需**：clone 仓库与安装器检查 |
| uv | 任意 | 一键脚本会自动安装（winget 或 GitHub 发布包），无需预装 |
| 模型 API Key | — | Anthropic / OpenAI / GLM(ZAI) / DeepSeek / Gemini / Kimi 等 |
| PostgreSQL | ≥ 14（可选） | 只在查库时安装；**只读账号**即可 |
| 日志目录 | 可选 | 不配则日志类诊断不可用 |

**只想看看效果？** 装完直接跑离线评测即可，不需要数据库、不需要 API Key：

```bash
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync
```

---

## 配置模型

```bash
cloudagent login
```

交互式写入 `~/.cloudagent/config.json`。也可以直接编辑：

```jsonc
{
  "default_provider": "zai",
  "providers": {
    "zai": { "api_key": "..." }
  }
}
```

环境变量优先级更高：`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `ZAI_API_KEY`。

## 配置只读数据库

诊断连库必须用**只读账号**。最小 SQL：

```sql
CREATE ROLE cloudagent_ro LOGIN PASSWORD '<自定>';
GRANT CONNECT ON DATABASE your_db TO cloudagent_ro;

-- 在每个需要诊断的库内执行：
GRANT USAGE ON SCHEMA public TO cloudagent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cloudagent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cloudagent_ro;
```

写进 `~/.cloudagent/config.json` 的 `env` 段：

```jsonc
{
  "env": {
    "CLOUDAGENT_DB_DSN": "postgresql://cloudagent_ro:pass@127.0.0.1:5432/your_db",
    "CLOUDAGENT_DB_DSN_SECONDARY": "postgresql://cloudagent_ro:pass@127.0.0.1:5432/your_db_downstream",
    "CLOUDAGENT_DB_QUERYABLE_TABLES": "orders,customers,devices,tenants"
  }
}
```

| 变量 | 作用 |
|---|---|
| `CLOUDAGENT_DB_DSN` | 主库（上游）连接串 |
| `CLOUDAGENT_DB_DSN_SECONDARY` | 下游库连接串；不配则只能单库诊断 |
| `CLOUDAGENT_DB_QUERYABLE_TABLES` | 允许查询的表白名单（逗号分隔）；不配则可查所有表 |

> ⚠️ `.env` 文件**不会**被读取。要么写 `config.json` 的 `env` 段，要么直接设进程环境变量。
> 早期版本曾支持 `.env`，现已移除——避免"改了不生效"的困惑。

## 配置日志目录

```jsonc
{
  "env": {
    "CLOUDAGENT_LOG_ROOT": "/var/log/my-service"
  }
}
```

要求：纯文本日志，每行尽量带时间戳与级别（`2026-10-22 09:00:00.120 INFO ...`）。
子目录会递归扫描；单文件过大时截断读取并给出提示。

---

## 验证安装

```bash
cloudagent --version                  # 版本
cloudagent doctor                     # 环境 / 配置 / Provider
cloudagent login                      # 配置模型 Key（首次）
cloudagent -p "orders 有没有同步到下游？"   # 需要模型 + 数据库
```

不需要模型和数据库的验证：

```bash
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --max-cases 1
pytest tests/diagnosis/security -q
```

## 常见安装问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `无法加载文件 … 未对文件进行数字签名` | PowerShell 执行策略 | 用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install` |
| `cloudagent: command not found`（新开终端仍没有） | PATH 未生效 | 重开终端；或 `./install.sh status` 看 PATH 条目 |
| `DSN not configured` | 没配连接串 | 见上文「配置只读数据库」 |
| `Failed to fetch: https://pypi.org/simple/...` / `tls handshake eof` | 依赖安装时连不上 PyPI | 配镜像后重试，如 `uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`，或在 `uv.toml` 里设 `[[index]]`；也检查代理/VPN |
| `Install target already exists and is not a standalone cloudagent install` | `-InstallDir` 指向了非空目录 | 换目录，或先清空 |
| `Missing: cloudagent_ext`（payload 校验失败） | **把 `-InstallDir` 指到了源码目录里**，安装器递归复制自身导致产物不完整 | 把安装目录放到源码目录**之外**，例如 `D:\apps\cloudagent` |
| 依赖安装失败（macOS） | 缺 PostgreSQL 头文件 | `brew install libpq` 后重试；或先不加 `[db]` |
| 安装失败不知原因 | — | 加 `-LogFile install.log` 收集完整日志，或跑 `.\install.ps1 doctor` |
| 想彻底重来 | — | `./install.sh uninstall` 后重新 install |

## 卸载

```bash
# 脚本安装
./install.sh uninstall

# 源码安装
pip uninstall cloudagent
rm -rf ~/.cloudagent        # 配置、凭据、会话记录
```
