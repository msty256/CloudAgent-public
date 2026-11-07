# 事故记录：模型调用静默失败（2026-11-07 12:20 更新）

> 触发：为 EVAL-P1b 取跨仓契约样本，跑 1 个真实 case。
> **两个独立问题叠加**，都已定位到根因。

## 结论速览

| # | 问题 | 性质 | 影响面 |
|---|---|---|---|
| **A** | `no_proxy` 含 `[::1]` → httpx 解析崩溃 | **本机环境**（非产品缺陷） | 所有走 httpx 的 provider |
| **B** | workbuddy provider 返回空、`model_calls=0`、无报错 | **待定**（产品 or 登录态） | 仅 workbuddy |

**关键澄清**：最初的 `AttributeError: 'UserMessage' has no attribute 'to_dict'` 是**我用错调用约定**（直接喂对象给 `chat`），**不是产品缺陷**。走正规路径不会有这个问题。

---

## 问题 A：代理环境变量导致 httpx 崩溃

### 现象

```
Provider: deepseek, Model: deepseek-ai/DeepSeek-V4.1-Flash-1017
Query error: Invalid port: ':1]'
exit: 1
```

### 根因

本机环境：
```
NO_PROXY = localhost,127.0.0.1,::1,[::1]     ← 注意方括号
http://127.0.0.1:7897  (HTTP_PROXY/HTTPS_PROXY)
```

httpx 0.28.1 解析 `no_proxy` 时把 `[::1]` 当成 `host:port`：

```
httpx/_client.py:698  URLPattern(key)
httpx/_urlparse.py:411  raise InvalidURL(f"Invalid port: {port!r}")
```

**与 cloudagent 代码无关**，是本机代理配置与 httpx 版本的兼容问题。

### 验证

在**移除所有代理环境变量**的干净子进程里跑同一个命令：

```python
env = dict(os.environ)
for k in ("no_proxy","NO_PROXY","HTTP_PROXY","HTTPS_PROXY",
          "http_proxy","https_proxy","ALL_PROXY","all_proxy"): env.pop(k, None)
subprocess.run([python, "-m", "cloudagent_ext.cli.main", "-p", "只回答两个字：OK",
                "--provider", "deepseek"], env=env)
```

**结果：`stdout = "OK"`，exit 0。** ✅

→ 问题 A 确认为环境侧。**用户可通过修正 `no_proxy`（去掉 `[::1]` 或全部删除）解决。**

---

## 问题 B：workbuddy 返回空

### 现象

干净环境下（无代理干扰）：

```
Provider: workbuddy, Model: deepseek-v4.1-flash
stdout: ''            ← 空
exit: 0
```

**exit 0 但没有任何回答**，也不报错。

### 已排除

| 假设 | 结论 |
|---|---|
| `to_dict` 缺失 | ❌ 排除——那是我用错调用约定 |
| 代理变量 | ❌ 排除——同一干净环境下 deepseek 正常 |
| agent loop 装配失败 | ❌ 排除——`prepare()` 成功，12 个工具、system_prompt 3844 字符 |
| eval_support 的问题 | ❌ 排除——`cloudagent -p` 日常路径同样复现 |

### 仍需确认

- workbuddy 的登录态是否过期（`has_key: False`，它走桌面登录态复用）；
- 是否 provider 内部把异常吞了（这是最可疑的点：**exit 0 + 空输出 + 无报错**）。

### 定性

**这是产品/provider 侧的问题，不是评测体系的问题。**
EVAL-P1a 反而忠实记录了它（`unfinished` + `model_calls=0` + `available=false`）。

---

## 对评测体系的影响

| 项 | 影响 |
|---|---|
| EVAL-P1b 跨仓样本 | **受阻**：拿不到真实 RunRecord（但总额度未消耗） |
| EVAL-P2 等价性验证 | 需要真实跑，若 provider 修不好则无从验证 |
| 离线路径 | **不受影响**（offline fixture 不调模型） |

**建议**：P1b 可先用 `deepseek` provider（已验证可用）+ 构造/真实样本推进，
不必等 workbuddy 修好。

---

## 额度

**两次尝试都未消耗 token**：
- 第一次：`model_calls=0, available=false`
- 第二次（workbuddy）：stdout 空、exit 0，同样无调用

→ 批准的 120 万 token 额度**一分未用**。

---

## 我的失误（两条）

1. **配错 `grade_source`**：`dispatch_mode=direct` + `grade_source=subagent` 是矛盾组合
   （direct 模式不产生子代理结果）。`RunRequest` 应拒绝这种组合，而不是跑到执行层才报错。
   → 记为 P1a 待改进项。

2. **误判 `to_dict` 是产品缺陷**：我在 `_probe_loop.py` 里直接 `provider.chat([UserMessage(...)])`，
   而正规路径传的是 dict 或经转换的对象。**用错调用约定导致误报**。
   → 教训：定位回归前，先用**产品自己的入口**复现（`cloudagent -p`），
     而不是自己拼调用链。
