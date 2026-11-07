# EVAL-P1a 审查结论 · 第二轮（复审 + 终审 PASS）

> 审查人：DSH Lead · 2026-11-07 12:10 · 分支 `feat/eval-p1a-runrecord`
> 上一轮：[`eval-p1a-round1.md`](./eval-p1a-round1.md)（PASS + 1 件待办）

## 结论：`PASS`（可合并）

round-1 §6 的待办已完成，且**追加了一条我没要求但很关键的防线**（见 §3）。

---

## 1. 待办完成情况

| round-1 §6 要求 | 实际 |
|---|---|
| `OUTCOME_STATUSES` 去掉 `"empty"` | ✅ 五档：`ok / timeout / crashed / unfinished / invalid_output` |
| `_determine_status()` 空输出 → `unfinished` | ✅ |
| `case_run_to_record()` 的 `"empty"` → `"unfinished"` | ✅ 两处（空输出分支 + "要子代理结果但没拿到"分支） |
| 用例同步（六档 → 五档） | ✅ |
| 文档不用动 | ✅ 未动（我改的） |

## 2. 我实跑的验收

| 闸门 | 结果 |
|---|---|
| `pytest tests/diagnosis/eval_support` | **65 passed** |
| `pytest tests/diagnosis` 全量 | **926 passed / 24 skipped** |
| `ruff check cloudagent_ext tests` | **All checks passed** |
| 反向依赖（排除 sanctioned 桥） | **`[]`** |
| 五档全部可往返 | ✅ 我逐档验证：`crashed/invalid_output/ok/timeout/unfinished` 每个都能正常序列化-反序列化 |
| `empty` 字面量残留 | 仅 1 处，在**解释性注释**里（"不是独立的 empty 档"）——正确，不是残留代码 |

## 3. 追加防线（我没要求，但很有价值）

```python
def test_rejects_removed_empty_status(self) -> None:
    """``empty`` 档已删除（审查裁决：空输出归 unfinished，与 categorize 一致）——
    写它会红，防止旧口径悄悄回流。"""
```

我实测确认它有效：

```python
record_from_json({... "outcome": {"status": "empty"} ...})
→ RunRecordError: outcome.status 必须是 ['crashed','invalid_output','ok','timeout','unfinished'] 之一，收到 'empty'
```

**为什么这条重要**：删枚举值最容易出的事故是"某个分支还写着旧值但没人发现"。
这条用例把"旧口径回流"变成编译期（测试期）可见的失败。
**这是我没有明确要求、但 ZCode 自己想到的**——正是我在这类任务里最希望看到的东西。

## 4. 代码改动复核

diff 我逐行看过，改动精确且注释到位：

```diff
-        return "empty", False
+        return "unfinished", False
```

```diff
-        # 请求要子代理结果但没拿到（如 main 模式没派发）→ graded_text 留空、status=empty
+        # 请求要子代理结果但没拿到（如 main 模式没派发）→ graded_text 留空、
+        # status 记 unfinished（空输出=没拿到作答机会，与 categorize 口径一致）
```

**没有顺手改别的东西**，diff 干净。

## 5. 关于"建议项未做"

你问的 `_wants_subagent_grade` 副本加 `# TODO(P2)` 标记——**决定：不做**。

理由：
1. 该函数在 `execute.py:132` 的 docstring 里**已经注明**"与 evaluation.executors._wants_subagent_grade 同语义（照抄不另立）"；
2. round-1 的 P2 待办清单已经把它列为"P2 搬迁后应改为从唯一实现导入"；
3. 再加一个 `TODO(P2)` 是**第三处重复记录**，反而增加维护面。

→ **随 P2 清单一起处理**，不单独加标记。

## 6. 合并

按你的指示，我执行合并。合并后 `main` 的 `tests/diagnosis` 应为 926 passed / 24 skipped。

## 7. 移交下一阶段

P1a 完成后，评测体系的"执行侧契约"就位。下一个是 **EVAL-P1b（评测仓骨架）**——
它需要在 `C:\Users\Administrator\Desktop\cloudagent-eval` 新建独立私有仓，
消费 P1a 产出的 RunRecord。

**注意 P1b 的前置条件**：它要用 P1a 导出的**真实 RunRecord 样本**做跨仓契约测试。
但 P1a 没跑真实 case（额度红线），所以样本只能来自：
- (a) 手工构造一份符合 schema 的 RunRecord（可行，但不能验证"真实产出长什么样"）
- (b) 跑 1 个真实 case（约 120 万 token）

→ 这个决策我在出 P1b 任务卡时会单独问你。
