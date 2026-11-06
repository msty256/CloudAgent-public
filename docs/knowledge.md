# 知识库检索（RAG）

诊断子 Agent 的**只读知识来源**：把历史诊断案例与项目设计文档做成可检索索引，
让 Agent 在给结论前先查"这类现象通常是什么原因、过去怎么处理"。

> 定位：知识是**证据**，不是结论。结论仍必须由 SQL / 日志 / 代码等数据证据支撑；
> 查不到时要显式说明"知识库无覆盖"。

## 数据来源

| 来源 | 位置 | 切块方式 |
|---|---|---|
| 历史诊断案例 | `cloudagent_ext/diagnosis/cases/**/*.json`（38 题） | 整条压成一块：`案例 / 领域 / 场景 + 问题 + 根因 + 建议 + 禁止结论` |
| 设计文档 | `docs/*.md` | 按 Markdown 标题分段（标题并入正文参与召回），超长段按 700 字符切、100 字符重叠 |

## 检索架构

```
用户问题
  ├─ BM25（中文二元组 + 英文词）──────────────┐
  └─ 稠密向量（bge-small-zh → FAISS）────────┤
                                            ├─ RRF(k=60) 按名次融合 → Top-K 片段
                                            ┘
```

| 层 | 实现 | 说明 |
|---|---|---|
| 关键词 | BM25（k1=1.5, b=0.75） | 认精确 token：表名、错误码、行号 |
| 语义 | **bge-small-zh-v1.5（512 维）+ FAISS IndexFlatIP** | mean pooling + L2 归一化，内积即余弦 |
| 降级 | TF-IDF 稀疏向量 | 无模型/无 faiss 时自动退回，功能不中断 |
| 融合 | RRF（Recursive Rank Fusion） | 只看名次，避免两种分数量纲不可比 |
| 重排 | **bge-reranker-base（交叉编码器）** | 可选，默认关闭；只对召回 Top-10 重排 |

**为什么混合**：语义问题（"数据没同步过去"）向量强；精确 token（`orders`、`E502`）BM25 强。
实测两者互补明显——见下方评测表。

**为什么还要重排**：向量检索是"双塔"——问题和文档**分开**编码，编码时互相看不见，所以只能算个大概。
重排是"交叉编码器"——把"问题 + 文档"拼成一条送进模型，让模型同时看着两段再打分。
精度高很多，但每条都要跑一次模型，所以**只对召回的前 10 条重排**，不做全库检索。

| 候选数 | 单次重排耗时（median） |
|---|---|
| 5 | 73 ms |
| **10（默认）** | **271 ms** |
| 20 | 751 ms |
| 40 | 1827 ms |

> 延迟随候选数近似线性增长（单条约 20ms）。诊断链路上超过 300ms 会明显拖慢体验，所以默认取 10。
> 重排默认**关闭**，设 `CLOUDAGENT_KB_RERANK=on` 才启用；模型缺失时静默保持原序。

## 安装

稠密检索是可选依赖，不影响主安装：

```bash
pip install -e ".[kb]"        # faiss-cpu + onnxruntime + tokenizers
```

模型文件放默认位置：

```
~/.cloudagent/models/bge-small-zh-v1.5/    # 向量模型（必需，~95MB）
    model.onnx
    tokenizer.json

~/.cloudagent/models/bge-reranker-base/    # 重排模型（可选，~280MB）
    model.onnx        # 用 onnx/model_quantized.onnx 量化版，原始 fp32 约 1GB
    tokenizer.json
```

可用环境变量覆盖：`CLOUDAGENT_BGE_MODEL`（向量模型目录）、`CLOUDAGENT_KB_DENSE=off`（强制稀疏）、
`CLOUDAGENT_KB_INDEX`（索引路径）、`CLOUDAGENT_RERANK_MODEL`（重排模型目录）、
`CLOUDAGENT_KB_RERANK=on`（启用重排，默认关闭）。

> 国内网络可用镜像：`https://hf-mirror.com/Xenova/<模型名>/resolve/main/...`
> 大文件单连接易断，建议分块并行下载（`Range` 头），实测 266MB 用 6 线程分块约 5 分钟。

## 构建索引

```bash
# 默认：案例 + docs/，同时生成 BM25 与 FAISS 向量（约 11s / 640 块）
python -m cloudagent_ext.diagnosis.knowledge.ingest

# 只要稀疏索引（无模型环境）
python -m cloudagent_ext.diagnosis.knowledge.ingest --sparse-only

# 自定义目录/输出（--cases/--docs 必须在仓库内，拒绝 ../ 逃逸）
python -m cloudagent_ext.diagnosis.knowledge.ingest \
    --cases cloudagent_ext/diagnosis/cases --docs docs \
    --out ~/.cloudagent/knowledge/index.json
```

产物（同一目录、同版本号，缺一不可）：

| 文件 | 内容 |
|---|---|
| `index.json` | 块清单 + 版本号（`version: 1`） |
| `index.faiss` | FAISS 向量索引（640 × 512 float32，约 1.3MB） |
| `index.ids.json` | 向量与 `chunk_id` 的对齐表 + 维度校验 |

索引是派生产物，**不进仓库**。重建时向量有磁盘缓存（按文本 sha1），不重复推理。

## 工具契约（`search_knowledge`）

| 项 | 说明 |
|---|---|
| 参数 | `query`（≤200 字，必填）、`top_k`（1..8，默认 5）、`domain`（sql/log/code/sync/cross，可选） |
| 返回 | `chunks[]`：`chunk_id / source / section / kind / domain / score / snippet`，外加 `total_chars`、`truncated`、`note`、`vector_backend` |
| 限额 | 单块 ≤700 字符、总字符 ≤6000、query ≤200 字符 |
| 只读 | `is_read_only=True`、`is_concurrency_safe=True`；无网络、无写操作 |
| 错误 | 索引缺失返回 `knowledge_index_missing`；参数非法返回 `KnowledgeQueryError`，均为结构化 `is_error` |

`vector_backend` 会返回 `dense` 或 `sparse`，便于观测当前走的是哪条路径。

证据引用：`chunk_id` 形如 `kb:cases/sync/sync-001.json#0`，在诊断协议里以
`ev:kb:<seq>` 参与 `evidence`，并分别填写 `proves` / `cannot_prove`。

## 评测

标注集 `eval/kb_queries.jsonl`（12 条人工标注 query，`expected` 支持多个可接受来源）：

```bash
python scripts/eval_kb.py                 # 三路召回对比
python scripts/eval_kb.py --rerank        # 额外跑「召回 + 重排」对比
```

**当前基线（654 块，12 条 query，2026-11-05）**

| 方式 | Recall@1 | Recall@3 | Recall@5 | MRR | p50 |
|---|---|---|---|---|---|
| BM25 | 66.7% | 91.7% | 100.0% | 0.808 | 1.18 ms |
| 稠密向量（bge） | 58.3% | 75.0% | 91.7% | 0.694 | 2.30 ms |
| **RRF 混合** | 75.0% | **100.0%** | **100.0%** | 0.861 | 1.99 ms |
| BM25 + 重排 | 83.3% | 100.0% | 100.0% | 0.889 | 80 ms |
| 稠密 + 重排 | 83.3% | 91.7% | 91.7% | 0.861 | 77 ms |
| **混合 + 重排** | **91.7%** | **100.0%** | **100.0%** | **0.944** | 101 ms |

**读法**（三点）：

1. **单看语义向量反而弱于 BM25**（91.7% vs 100%）：小语料 + 中文技术文档术语密集，字面匹配本就强。
2. **RRF 融合后 Top-1 与 MRR 超过两路单打**：两路互补，不是重复劳动——这是"为什么要混合"的实证。
3. **重排把 Top-1 从 75% 提到 91.7%、MRR 从 0.861 提到 0.944**，但 p50 从 2ms 涨到 101ms。
   **用 50 倍延迟换 16 个百分点的 Top-1**，是否值得取决于场景——诊断是人在等，所以我默认关闭、需要时开。

> 只评估**检索层**；诊断结论质量看 38 题评分器，两套指标不要混。
> 自检索（用案例自己的问题查自己）是循环验证，只能证明链路通，不作效果指标。
> 样本仅 12 条，百分比波动大，面试应说明"小样本、用于机制验证"。

## 安全边界

1. **只读**：工具无写操作、无网络；索引构建只读 `cases/` 与 `docs/`，路径必须落在仓库内。
2. **数据不是指令**：检索文本按不可信数据处理，工具/技能说明中明确不执行其中指令；
   专门测试覆盖"文档里写忽略指令"（`tests/diagnosis/knowledge/test_data_boundary.py`）。
3. **有限额**：query / 单块 / 总字符都有上限，避免把超大文本塞进上下文。
4. **本地推理**：bge 在本机 ONNX 运行，文本不出机器。

## 测试

```bash
python -m pytest tests/diagnosis/knowledge -q   # 66 项
```

覆盖：切块与去重、BM25/稀疏/稠密三路检索、RRF 融合、FAISS 存取与版本校验、
embedder 降级（无模型 → NullEmbedder → 稀疏检索）、重排逻辑与降级、
工具契约与结构化错误、路径逃逸、数据边界。

> 测试不依赖真实模型（用 FakeEmbedder / FakeReranker），CI 无 bge 也能跑；
> 真实模型效果由 `scripts/eval_kb.py --rerank` 验证。
