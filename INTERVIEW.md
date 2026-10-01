# 面试速览 · Demo 手册

> 一页版：只保留现场要**讲**的和要**演**的。完整文档见 [README.md](README.md)。

## 30 秒介绍

企业内部知识问答 Agent：员工用自然语言提问，系统自主完成**意图识别 → 工具调用 → 知识检索 → 回答生成 → 结果反思**。
自建 Planner-Executor-Reflector 框架（不依赖 LangChain），FastAPI + FAISS + qwen-flash，前端 React 19 走 SSE 流式打字机。
两个最想让人看到的能力：**检索质量阈值拦幻觉**、**多轮记忆（摘要压缩 + 会话缓存）在多工具 Agent 里真的生效**。

## 架构一图流

```
   React 前端 :5173
   聊天界面(SSE 打字机) · 知识库浏览(条数/内容)
        │ POST /api/v1/agent/stream
        ▼
   FastAPI :8000        app/api/chat.py · app/api/agent.py · app/admin/knowledge.py
        │
        ▼
   AgentLoop（会话缓存 OrderedDict + Lock，LRU 上限 100）
     ① Memory    短期(内存，15 轮触发摘要压缩) + 长期(profile 落盘)
     ② Planner   规则层(0 Token) → 大模型 JSON 计划 │ 大模型挂 → 降级话术
     ③ Executor  rag_query / memory_retrieval / direct_response / 工具注册表调度
     ④ Reflector 执行失败降级 · 偏好补存 · 回答过短转检索（≤3 轮）
     ⑤ Trace     全链路 trace_id + 每步耗时
        │
        ├─ rag.py  检索 → 阈值评估 → 生成（answer / answer_stream）
        ├─ tools/  rag_query · calculator · http_request
        └─ utils/  llm(重试/流式) · sse · embedding · config
        ▼
   DashScope  qwen-flash  +  text-embedding-v4(1024)  +  FAISS(IndexFlatL2)
```

## 五个必讲的设计点

1. **规则层 + 大模型双层决策**：关键词硬匹配做确定性路由，命中即 0 Token、毫秒返回；只有模糊意图才问大模型 → 省钱、稳、可解释。
2. **检索质量阈值拦幻觉**：`score` 是余弦相似度，最高分 < `RAG_SCORE_THRESHOLD`(0.48) 时**不调用大模型**，直接返回「未找到相关内容」。
3. **容错与降级**：`call_llm_with_retry` 指数退避重试 1→2→4s，重试耗尽返回「当前服务繁忙，请稍后重试。」；流式一旦已产出内容不再重试，避免重复输出。
4. **记忆分层**：短期（会话内，超 15 轮把最早 5 轮压成 ≤100 字摘要，以 `role="system"` 放回 history 开头）+ 长期（画像落盘）+ 会话缓存（`{user_id: Memory}` + LRU 100，重启即清空，明确取舍）。
5. **任何动作都有兜底**：Executor 按工具参数签名调度；参数不全或动作未实现时回退知识库检索，绝不把 `未知操作: xxx` 这类内部字符串抛给用户。

## 演示脚本（8 步，约 5 分钟）

**Step 0 启动**（两个终端）
```bash
uvicorn app.main:app --reload          # 看到 [OK] 配置验证通过 / 加载已有向量库，共 12 条记录
cd frontend && npm run dev             # http://localhost:5173
```

**Step 1 正常 RAG**：问「年假怎么申请」
→ 答年假天数、飞书提交、经理审批；后端日志 `检索相关性通过，最高分 0.6248 >= 阈值 0.3`
> 讲：答案来自知识库，不是模型记忆。

**Step 2 幻觉抑制**：问「今天天气怎么样」
→ 答「未找到与您问题直接相关的内容，建议您换一种问法或咨询相关部门。」
> 日志 `检索相关性不足，最高分 0.1163 < 阈值 0.3，跳过调用大模型`
> 讲：这一类问题没有浪费 Token，也没有让模型编。

**Step 3 多工具**：问「帮我算一下 128*7」→ `计算结果: 128*7 = 896`，`action=calculator`
> 讲：工具注册表 + Planner 选择，新增工具只需实现 `BaseTool` 并注册。

**Step 4 流式**：前端随便问一句，看逐字出现；或命令行验证
```bash
curl.exe -N -X POST http://localhost:8000/api/v1/agent/stream -H "Content-Type: application/json" -d "{\"question\":\"年假怎么申请\",\"user_id\":\"demo\"}"
```
> 讲：SSE 事件 `data: {"content":"..."}` + `data: [DONE]`；首块约 2 秒；前端用 `getReader()` 而不是 `EventSource`（后者只支持 GET、不能带 body）。

**Step 5 记忆**：连续 16 轮「第 N 个问题，我叫王磊」，再问「我叫什么名字」「我前面提到过什么」
→ 答「您之前多次提到您叫王磊。」/ 列出前几轮要点
> 日志会打印 `历史对话已压缩：摘要 46 字，保留最近 10 轮对话`（第 15 轮触发）
> 讲：history 首条变成 `role="system"` 的摘要 + 最近 10 轮。

**Step 6 容错降级**：把 `.env` 的 Key 改错（或断网）重启后端，再问一句
→ 返回「当前服务繁忙，请稍后重试。」，HTTP 仍是 200；日志两条重试 WARNING
> 讲：重试是带指数退避的，最后兜底，接口不 500、不崩。

**Step 7 知识库管理**：点侧边栏「查看知识库」看 12 条（text + source）；或
```bash
curl.exe http://localhost:8000/api/v1/admin/knowledge/list
```

**Step 8（可选）看日志**：`logs/app_YYYY-MM-DD.log` 里能看到一次请求的完整链路
```
[Trace 29709fc2] planner 开始 → Planner 决策: {...}
[Trace 29709fc2] rag_stream 完成，耗时 2264.61ms → 总耗时 2269.06ms
```

## 面试官可能追问

| 问题 | 30 秒回答 |
| --- | --- |
| 为什么不用 LangChain？ | 核心链路自己写约几百行，依赖少、行为完全可控；Planner 输出是 JSON，每步都有 Trace，出问题能定位到具体步骤。 |
| 阈值 0.48 怎么定的？ | 实测分布定：库内问题最高分 0.58~0.82，库外 0.19~0.38，取两者之间偏安全的值；日志会打印实际最高分，扩容知识库后重新校准。 |
| 为什么不做 rerank / 混合检索？ | 知识库只有 12 条、单文件切段，rerank 收益不明显；检索被隔离在 `RAGService._retrieve_relevant`，规模化后加 BM25 混合 + rerank 不用动上层。 |
| 摘要压缩的参数？ | 15 轮触发、压缩最早 5 轮，使历史回到 10 轮内；摘要失败回退直接截断并记 WARNING，主流程不受影响。 |
| 短期记忆为什么不落盘？ | 明确取舍：避免每轮写盘，重启后丢会话上下文可接受；长期偏好已经落 `user_profiles.json`，需要时可加 `sessions/<user_id>.json`。 |
| 并发安全怎么保证？ | 会话缓存用 `OrderedDict` + `threading.Lock`，FastAPI 的同步生成器在线程池里迭代；向量库是进程内单例，写操作集中在 admin 接口，生产环境应拆成独立服务并加锁。 |
| 大模型挂了会怎样？ | Planner 拿到 `None` 就返回 `action=degraded` 的降级话术；RAG 侧返回「当前服务繁忙」；流式侧会补发兜底事件，客户端不会拿到半截回答。 |
| 效果怎么评估？ | 目前是 8 条端到端验收用例 + 检索分数与 action 日志；下一步按 RAGAS 思路加拒答准确率、命中率、答案忠实度的离线评测集。 |
| Token 成本？ | 规则层挡掉一部分请求完全不花 Token；一次问答通常是 1 次 embedding + 1 次生成；qwen-flash 单次回答成本极低。 |
| 前端为什么这么简单？ | 面试演示只需要把「流式 + 知识库可视化」讲清楚；用 fetch + CSS 手写，不引路由/状态库，代码量小、无构建复杂度。 |

## 现场改代码的话，改动点在哪

| 想演示 | 改哪里 |
| --- | --- |
| 调检索严格度 | `app/utils/config.py` 的 `RAG_SCORE_THRESHOLD` |
| 加业务关键词（0 Token 路由） | `app/core/rules.py` 的 `KEYWORD_RULES` |
| 接入新工具 | 实现 `app/tools/base_tool.py` 子类并注册到 `app/tools/__init__.py` |
| 改模型 / 重试策略 | `app/utils/config.py` 的 `LLM_MODEL` / `MAX_RETRIES` / `RETRY_DELAY` |
