# 同步诊断演示（方案 A：定时同步故障，不涉及 Kafka 状态）
# 前置：本机 PostgreSQL:5433（cloudagent_sim）+ logs-sim + 模型配置
# 注意：本脚本依赖本机环境，CI 不可复现。

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "未找到 $python，请先创建 .venv" }

# 环境摘要（便于区分"环境问题"与"诊断问题"）
$dsnFile = Join-Path $HOME ".cloudagent\db_sim.env"
$hasDsn = Test-Path $dsnFile
$logs = Join-Path $repo "logs-sim"
Write-Host "=== 环境摘要 ==="
Write-Host ("DSN 配置文件: {0}" -f $(if ($hasDsn) { "有" } else { "缺失（live 取数会失败）" }))
Write-Host ("日志目录: {0} ({1} 个文件)" -f $logs, (Get-ChildItem $logs -File -ErrorAction SilentlyContinue).Count)
Write-Host ("模型配置: {0}" -f $(if (Test-Path (Join-Path $HOME ".cloudagent\config.json")) { "有" } else { "缺失" }))

if ($hasDsn) {
    Get-Content $dsnFile | ForEach-Object {
        if ($_ -match "^\s*CLOUDAGENT_DB_DSN\s*=\s*(.+)$") { $env:CLOUDAGENT_DB_DSN = $Matches[1].Trim('"') }
    }
}

Write-Host "=== 运行 live 同步诊断（sync 域）==="
& $python -m cloudagent_ext.diagnosis.evaluation.runner --mode live --domain sync --variant gaps-on
if ($LASTEXITCODE -ne 0) { throw "评测失败（退出码 $LASTEXITCODE）" }

$latest = Get-ChildItem (Join-Path $repo "eval\runs") -Directory | Sort-Object Name -Descending | Select-Object -First 1
Write-Host ("报告：{0}" -f (Join-Path $latest.FullName "summary.md"))
