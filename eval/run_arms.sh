#!/usr/bin/env bash
# 缩减版 L3：3 例 × 4 臂 × 1 轮
set -u
CASES="log-004,log-005,log-006"
for V in baseline arm:state arm:inval arm:reduce; do
  echo "=============== ARM: $V ==============="
  PYTHONPATH='.;extensions/lkb/src' timeout 2000 \
    "C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe" \
    -m cloudagent_ext.diagnosis.evaluation.runner \
    --mode live --dispatch main --domain log \
    --cases "$CASES" --variant "$V" --timeout-per-case 500 2>&1 \
    | grep -E "Top-1 根因命中率:|Top-3 根因命中率:|证据充分率:|无法诊断率:|报告："
done
echo "=============== ALL DONE ==============="
