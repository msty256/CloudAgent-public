# 安装与配置

从零到能跑一次诊断。全部命令以 macOS / Linux 为主，Windows 用括号内的写法。

## 环境要求

| 项 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.11 | 3.11 / 3.12 / 3.13 均已验证 |
| 模型 API Key | — | 支持 Anthropic / OpenAI / GLM(ZAI) / DeepSeek / Gemini / Kimi 等 |
| PostgreSQL | ≥ 14（可选） | 只在需要查库时安装；只读账号即可 |
| 日志目录 | 任意（可选） | 通过环境变量指定；不配则日志类诊断不可用 |

**只想试一下？** 装完依赖直接跑离线评测即可，不需要数据库、不需要 API Key（见文末）。

## 安装

```bash
git clone https://github.com/<you>/CloudAgent.git
cd CloudAgent

python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate

pip install -e ".[db]"               # [db] 只在需要查库时加
```

验证安装：

```bash
cloudagent --version
cloudagent diag
```

`diag` 会打印版本、配置路径、模型 Provider、可用工具数量；任一项异常会明确指出来。

## 配置模型

```bash
cloudagent login
```

交互式写入 `~/.cloudagent/config.json`。也可以直接编辑该文件：

```jsonc
{
  "default_provider": "zai",
  "providers": {
    "zai": { "api_key": "..." }
  }
}
```

或用环境变量（优先级高于配置文件）：`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `ZAI_API_KEY`。

## 配置只读数据库

诊断需要连库时，必须有**只读账号**。建账号的最小 SQL：

```sql
CREATE ROLE cloudagent_ro LOGIN PASSWORD '<自定>';
GRANT CONNECT ON DATABASE your_db TO cloudagent_ro;

-- 在每个需要诊断的库内执行：
GRANT USAGE ON SCHEMA public TO cloudagent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cloudagent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cloudagent_ro;
```

然后把连接串写进 `~/.cloudagent/config.json` 的 `env` 段：

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
| `CLOUDAGENT_DB_DSN_SECONDARY` | 下游库连接串，用于上下游对账；不配则只能单库诊断 |
| `CLOUDAGENT_DB_QUERYABLE_TABLES` | 允许查询的表白名单（逗号分隔）；**不配则所有表都可查** |

> ⚠️ `.env` 文件**不会**被读取。配置要么写 `config.json` 的 `env` 段，要么直接设进程环境变量。
> 早期版本曾支持 `.env`，现已移除，避免"改了不生效"的困惑。

## 配置日志目录

```jsonc
{
  "env": {
    "CLOUDAGENT_LOG_ROOT": "/var/log/my-service"
  }
}
```

要求：目录下是**纯文本日志**，每行尽量带时间戳与级别（形如 `2026-10-22 09:00:00.120 INFO ...`）。
子目录会被递归扫描，单文件过大时会被截断读取并给出提示。

## 验证

```bash
# 1. 自检
cloudagent diag

# 2. 离线评测（不连库、不调模型）
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync

# 3. 只读安全套件（应全部通过）
pytest tests/diagnosis/security -q

# 4. 真实提问（需要模型 + 数据库）
cloudagent -p "orders 有没有同步到下游？"
```

## 卸载

```bash
pip uninstall cloudagent
rm -rf ~/.cloudagent          # 配置、凭据、会话记录
```
