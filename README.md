# 智核 · 企业知识 MCP 中枢

**智核** 是一个面向企业内部的智能问答 Agent，同时把企业知识能力以 MCP（Model Context Protocol）工具的形式标准化对外暴露。

员工用自然语言提问，系统自主完成「意图识别 → 任务分解 → 工具调用 → 知识检索 → 回答生成 → 结果汇总」，并在检索不到依据时主动拒答，而不是让大模型硬答编造。既可以通过自带的 React 界面使用，也可以被 Claude Desktop、Cursor 等 MCP 客户端直接调用。

- 检索质量阈值拦幻觉：相似度不达标直接拒答，不浪费 Token、不给模型编造的机会
- 自建轻量 Agent 框架：手写 Planner / Executor / Reflector，约几百行核心代码，行为完全可控
- 多步任务分解：多诉求问题先拆成子任务，逐个执行后由一个回答汇总输出
- 5 个企业知识 MCP 工具：知识问答、跨文档检索、文档摘要、结构化抽取、长期记忆

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [架构设计](#架构设计)
- [项目结构](#项目结构)
- [快速启动](#快速启动)
- [API 接口](#api-接口)
- [MCP 服务器](#mcp-服务器)
- [任务分解](#任务分解)
- [配置项](#配置项)
- [关键设计决策](#关键设计决策)
- [可观测性](#可观测性)
- [实测验收](#实测验收)
- [常见问题与排错](#常见问题与排错)
- [已知限制与后续优化](#已知限制与后续优化)

## 功能特性

| 能力 | 说明 |
| --- | --- |
| RAG 问答 | 先检索企业知识库，再让大模型基于参考资料回答，System Prompt 强制「只依据参考资料」 |
| 检索质量评估 | 最高相似度低于阈值直接拒答，不调用大模型，抑制幻觉 |
| Agent 规划 | 规则层关键词硬匹配（0 Token）+ 大模型判断模糊意图，两层决策 |
| 任务分解 | 多诉求问题（对比 / 然后 / 分别 / 以及）先拆成子任务，逐个执行后由一个回答汇总输出 |
| 多工具调度 | 工具注册表统一管理 6 个工具，Planner 选择、Executor 调度 |
| 三层记忆 | 短期记忆（会话内，含摘要压缩）、长期记忆（跨会话画像落盘）、工作记忆（Trace） |
| 反思机制 | Reflector 校验执行结果，必要时降级或切换工具重试（最多 3 轮） |
| 容错降级 | 大模型调用按指数退避重试，重试耗尽返回固定话术，接口不报错、不崩溃 |
| 流式输出 | SSE 逐块下发，首块约 2 秒到达（本机实测 2.07s），无需等待整段生成 |
| MCP 服务器 | 5 个企业知识工具通过 MCP 协议暴露（SSE + stdio），带 Bearer Token 鉴权与调用日志 |
| 可观测性 | 全链路 Trace ID，记录 Planner → Executor → Reflector 每一步输入输出与耗时 |
| 知识库管理 | 增量添加 / 列表 / 删除接口，前端可查看条目数量与内容 |
| 前端演示 | 聊天界面（打字机效果）+ 知识库浏览弹层，开箱即用 |

## 技术栈

| 层次 | 选型 |
| --- | --- |
| 后端 | Python 3.11+（本机实测 3.14.5）+ FastAPI + Uvicorn |
| 大模型 | 通义千问 `qwen-turbo`（DashScope SDK，含指数退避重试与降级） |
| 向量检索 | FAISS（IndexFlatL2）+ 百炼 `text-embedding-v2`（1536 维）+ 余弦相似度阈值兜底 |
| Agent 架构 | 自建 Planner-Executor-Reflector 框架（ReAct 思路），不依赖 LangChain |
| 记忆 | 短期记忆（内存，含摘要压缩）+ 长期画像（`data/memory/user_profiles.json`）+ Trace |
| MCP | FastMCP（mcp 1.x）+ 自研 MCP 服务器，同时支持 SSE 与 stdio |
| 前端 | React 19 + Vite，只用 fetch + CSS（无路由库 / 状态库 / UI 框架） |
| 日志 | 控制台 + 按日切分文件（UTF-8），全链路 Trace ID |

## 架构设计

### 分层

- **API 层**：只负责路由、参数校验、把流式生成器包成 SSE 响应，不含业务逻辑
- **业务层 Core**：Planner（规划）、TaskDecomposer（分解）、Executor（执行）、Aggregator（汇总）、Reflector（反思）、Memory（记忆）、AgentLoop（主循环）、RAGService（检索问答）
- **工具层 Tools**：`BaseTool` 抽象 + 注册表，新增工具只需实现 `execute` 并注册进 `app/tools/__init__.py`
- **基础层 Utils**：配置、日志、LLM、Embedding、SSE、Trace，面向接口设计，替换底层不影响上层

### 一次 Agent 请求的处理流程

```
用户提问
└─ AgentLoop.run / run_stream
   ├─ 1. 取会话级 Memory（缓存命中则复用，否则新建并纳入 LRU）
   │      写入本轮用户消息，取出对话上下文与用户画像
   ├─ 2. Planner 规划
   │      ├─ 多诉求关键词命中 → TaskDecomposer 拆解 → mode = multi_step
   │      ├─ 规则层命中（年假 / 报销 / 加班…）→ 直接返回计划，0 Token
   │      └─ 未命中 → 大模型输出 JSON 计划；大模型不可用 → 返回 None
   │              └─ 上层降级：直接返回「当前服务繁忙，请稍后重试。」
   ├─ 3. Executor 执行（multi_step 时逐个子任务执行）
   │      ├─ rag_query         → RAGTool → 检索 → 阈值评估 → 生成回答
   │      ├─ memory_retrieval  → 基于历史摘要 / 长期画像回答
   │      ├─ direct_response / clarify → 固定话术
   │      └─ 其他动作           → 按工具注册表调度；参数不全则回退知识库检索
   ├─ 4. Aggregator 汇总（仅 multi_step）：把各子任务结果融会贯通成一段回答
   ├─ 5. Reflector 反思（最多 3 轮，仅单步链路）
   │      执行失败 → 降级为 direct_response
   │      表达了偏好但未落库 → 转 memory_retrieval 重新执行
   │      直接回答过短 → 转 rag_query 补充检索
   └─ 6. 写回助手消息、结束 Trace、返回 answer / action / reasoning
```

流式链路（`run_stream`）复用同样的规划与记忆：`action == "rag_query"` 走流式生成逐块下发，其他意图一次性返回；流式不做反思重试，避免客户端长时间没有输出。

## 项目结构

```
enterprise_kb_agent/
├── app/
│   ├── api/                  # 接口层：只做路由与参数校验
│   │   ├── chat.py           #   /api/v1/chat、/api/v1/chat/stream
│   │   └── agent.py          #   /api/v1/agent、/api/v1/agent/stream
│   ├── admin/
│   │   └── knowledge.py      # 知识库管理：增量添加 / 列表 / 删除
│   ├── core/                 # 业务层
│   │   ├── agent_loop.py     #   Agent 主循环 + 会话级记忆缓存（LRU）
│   │   ├── planner.py        #   任务规划：规则层 + 大模型 + 多步判断
│   │   ├── task_decomposer.py #  任务分解：多诉求问题拆成子任务列表
│   │   ├── aggregator.py     #   汇总器：把子任务结果融合成一个回答
│   │   ├── rules.py          #   规则层：关键词硬匹配，0 Token
│   │   ├── executor.py       #   执行器：工具调度、记忆检索、兜底
│   │   ├── reflector.py      #   反思器：结果校验与重试
│   │   ├── rag.py            #   RAG 服务：检索 → 阈值评估 → 生成（含流式）
│   │   ├── vector_store.py   #   FAISS 向量库封装（增 / 查 / 持久化）
│   │   └── memory.py         #   短期记忆（摘要压缩）+ 长期画像
│   ├── tools/                # 工具层：注册表 + 可扩展工具
│   │   ├── base_tool.py      #   工具抽象基类
│   │   ├── rag_tool.py       #   rag_query
│   │   ├── calculator.py     #   calculator
│   │   ├── http_request.py   #   http_request（演示工具调用链路）
│   │   ├── multi_doc_search.py    # multi_doc_search：跨文档检索并按来源分组
│   │   ├── summarize_document.py  # summarize_document：文档摘要
│   │   └── extract_structured.py  # extract_structured：结构化字段抽取
│   ├── utils/                # 基础层
│   │   ├── config.py         #   全部可调参数集中在此
│   │   ├── llm.py            #   大模型封装：重试、流式、messages 拼装
│   │   ├── embedding.py      #   百炼 Embedding 封装
│   │   ├── sse.py            #   SSE 事件与响应头封装
│   │   ├── logger.py         #   控制台 + 按日切分文件日志
│   │   └── observability.py  #   Trace 与步骤耗时
│   ├── mcp_server.py         # MCP 服务器：5 个企业知识工具 + 鉴权 + 调用日志
│   └── main.py               # 服务入口：配置校验、CORS、路由注册、挂载 MCP
├── data/
│   ├── knowledge/policies.txt     # 知识源文件（按空行切段）
│   ├── vectors/                   # FAISS 索引 + 元数据（构建后生成）
│   └── memory/user_profiles.json  # 长期用户画像（运行后生成）
├── frontend/                 # React 前端，详见下方「前端」一节
├── build_knowledge_base.py   # 构建知识库（全量）
├── add_knowledge.py          # 增量添加知识（调用 HTTP 接口）
├── reset_knowledge.py        # 重置知识库
├── test_api.py               # 冒烟脚本：/api/v1/chat
├── test_agent.py             # 冒烟脚本：/api/v1/agent
├── test_memory.py            # 冒烟脚本：HTTP 记忆链路
├── test_memory_terminal.py   # 冒烟脚本：直接调用 AgentLoop
├── requirements.txt
├── .env.example              # 环境变量模板（DASHSCOPE_API_KEY / MCP_AUTH_TOKEN）
├── README.md                 # 本文档
└── INTERVIEW.md              # 面试速览：一页版演示脚本与追问回答
```

## 快速启动

### 0. 前置要求

- Python 3.11+（本机实测 3.14.5）
- Node.js 18+（本机实测 v24.21）
- 一个 DashScope（阿里云百炼）API Key

```bash
# Windows 建议先建虚拟环境
python -m venv venv
venv\Scripts\activate
```

### 1. 配置环境变量

复制模板并填入自己的 Key（`cp .env.example .env`，或直接在项目根目录新建 `.env`）：

```
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

用 `python-dotenv` 加载；启动时 `Config.validate()` 会校验，缺失会直接退出并打印 `[ERROR] 配置错误`。

### 2. 启动后端

```bash
pip install -r requirements.txt        # 依赖较多，国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple
python build_knowledge_base.py         # 首次必做：构建向量库，并打印一次检索测试结果
uvicorn app.main:app --reload          # http://localhost:8000 ，交互文档 /docs
```

启动成功会看到 `[OK] 配置验证通过` 与「加载已有向量库，共 12 条记录」。

### 3. 启动前端

```bash
cd frontend && npm install
cd frontend && npm run dev             # http://localhost:5173
```

前端默认请求 `http://localhost:8000`，后端已在 `app/main.py` 配置 CORS 放行 `http://localhost:5173`。

### 4. 验证

```bash
curl http://localhost:8000/health
curl http://localhost:8000/mcp      # MCP 服务信息页（含工具列表与鉴权状态）
python test_agent.py                # 或浏览器打开 http://localhost:5173 直接提问
```

常用维护脚本：

```bash
python add_knowledge.py             # 增量添加知识（需要后端已启动）
python reset_knowledge.py           # 清空并重建知识库
```

### 5. 接入 MCP 客户端（可选）

后端启动后即可用 MCP 客户端连接 `http://localhost:8000/mcp/sse`；也可以不依赖后端，用 `python -m app.mcp_server` 以 stdio 方式独立运行。配置示例见下方「MCP 服务器」。

## 前端

```
frontend/
├── index.html
├── package.json
├── vite.config.js
└── src/
    ├── main.jsx
    ├── App.jsx       # 聊天界面 + 知识库弹层 + SSE 流式解析
    ├── App.css       # 主色 #1a73e8，气泡圆角，输入框固定底部
    └── index.css     # 全局重置
```

- 页面加载时拉 `/api/v1/admin/knowledge/list`，侧边栏显示「知识库条目：N 条」，点「查看知识库」弹出全部条目（text + source）
- 发送问题时 POST `/api/v1/agent/stream`，用 `response.body.getReader()` 读流，逐块解析 `data: {"content": "..."}` 并追加到当前 AI 气泡，实现打字机效果；收到 `data: [DONE]` 结束
- `user_id` 用 `localStorage` 持久化一个随机 UUID，保证同一浏览器多轮对话共用同一份会话记忆
- 后端未启动或请求失败时提示「服务连接失败，请确认后端已启动」

## API 接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/v1/chat` | POST | 基础对话（纯 RAG 问答） |
| `/api/v1/chat/stream` | POST | 流式对话（SSE，边生成边返回） |
| `/api/v1/agent` | POST | 完整 Agent 对话（规划 + 工具调用 + 记忆 + 反思） |
| `/api/v1/agent/stream` | POST | 流式 Agent 对话（SSE，边生成边返回） |
| `/api/v1/admin/knowledge/add` | POST | 增量添加知识条目 |
| `/api/v1/admin/knowledge/list` | GET | 知识库列表（返回 `items` 与 `total`） |
| `/api/v1/admin/knowledge/delete/{doc_id}` | DELETE | 删除指定知识条目（全量重建索引） |
| `/health` | GET | 健康检查 |
| `/mcp` | GET | MCP 服务信息页（服务名、工具列表、鉴权状态） |

请求体：

```json
// POST /api/v1/chat
{ "question": "年假怎么申请" }

// POST /api/v1/agent
{ "question": "年假怎么申请", "user_id": "test_user" }
```

响应体（非流式 Agent）：

```json
{ "success": true, "answer": "……", "action": "rag_query", "reasoning": "……" }
```

流式事件格式：

```
data: {"content": "根据"}

data: {"content": "企业年假制度"}

data: [DONE]
```

流式调用示例：

```bash
curl -N -X POST http://localhost:8000/api/v1/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"年假怎么申请","user_id":"test_user"}'
```

> 前端用 `fetch` + `response.body.getReader()` 而不是 `EventSource`，因为 `EventSource` 只支持 GET、无法携带 body。

## MCP 服务器

「智核」把企业知识能力以 MCP（Model Context Protocol）协议标准化暴露，任何支持 MCP 的客户端都能直接调用，无需关心后端的 HTTP 细节。原则是**只暴露企业知识相关工具**，不掺天气、汇率这类通用工具。

### 工具列表

| 工具 | 入参 | 说明 |
| --- | --- | --- |
| `rag_query` | `question` | 查询企业知识库，回答公司政策、制度、流程问题（内部走完整的检索 → 阈值评估 → 生成） |
| `multi_doc_search` | `query`、`top_k=5` | 跨多份文档检索，按来源文档分组返回相关段落，适合对比多个制度、政策、合同条款 |
| `summarize_document` | `doc_name`、`max_length=200` | 取出该文档的全部段落交给大模型生成摘要，提取关键条款 |
| `extract_structured` | `text`、`fields`（逗号分隔） | 从非结构化文本中抽取指定字段，返回键值对，文本中未提及的字段填「未提及」 |
| `memory_retrieval` | `user_id`、`type=preference\|history` | 读取该用户的长期记忆（偏好或历史查询） |

### 端点与运行方式

| 端点 / 命令 | 说明 |
| --- | --- |
| `GET /mcp` | 服务信息页（服务名、工具列表、鉴权状态），便于确认端点可达 |
| `GET /mcp/sse` | SSE 通道，MCP 客户端从这里建立连接 |
| `POST /mcp/messages/` | 客户端消息回传通道 |
| `python -m app.mcp_server` | 以 stdio 方式独立运行，供本地客户端直接拉起进程 |

### Claude Desktop 配置示例

SSE 方式（写入 `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "zhihe-knowledge": {
      "url": "http://localhost:8000/mcp/sse",
      "headers": { "Authorization": "Bearer <MCP_AUTH_TOKEN>" }
    }
  }
}
```

本地进程方式（不依赖后端服务，直接拉起 MCP 进程）：

```json
{
  "mcpServers": {
    "zhihe-knowledge": {
      "command": "C:\\Users\\xcy\\Desktop\\enterprise_kb_agent\\venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:\\Users\\xcy\\Desktop\\enterprise_kb_agent"
    }
  }
}
```

### Cursor 配置示例

写入 `.cursor/mcp.json`（项目级）或 `~/.cursor/mcp.json`（全局）：

```json
{
  "mcpServers": {
    "zhihe-knowledge": { "url": "http://localhost:8000/mcp/sse" }
  }
}
```

### 认证说明

- 在 `.env` 里配置 `MCP_AUTH_TOKEN` 后，除 `GET /mcp` 信息页外，所有 MCP 请求都必须带 `Authorization: Bearer <token>`，缺失或错误一律返回 `401`
- `MCP_AUTH_TOKEN` 为空时跳过校验（本地开发 / 演示模式），启动日志与 `/mcp` 信息页都会显示当前鉴权状态
- 实测结果：无 Token → `401`、错误 Token → `401`、正确 Token → 成功建立 SSE 连接并调用 5 个工具

### 调用日志

调用日志单独写入 `logs/mcp_YYYYMMDD.log`，通过装饰器统一记录：

```
[OK]       工具 rag_query      参数 {...}  耗时 1830.42ms  返回 118 字
[ERROR]    工具 summarize_document  参数 {...}  耗时 512.07ms  错误 ...
```

## 任务分解

单步问题（如「年假怎么申请」）直接走 Planner → Executor；包含多个诉求的问题会先被拆成子任务，逐个执行后再汇总成一个回答。

### 触发条件

问题里出现 `对比` / `然后` / `分别` / `以及` 任意一个关键词，并且 `ENABLE_TASK_DECOMPOSITION = True`（默认开启）：

1. 先交给 `TaskDecomposer`（`app/core/task_decomposer.py`）拆解，最多 `MAX_SUBTASKS` 个子任务
2. 拆解成功 → Planner 返回 `{"mode": "multi_step", "subtasks": [...]}`
3. 拆解失败（大模型不可用或返回无法解析）→ 自动回退到单步规划，不影响原有行为

拆解结果只有 1 个子任务时仍会走多步链路（多一次汇总调用），所以提示词要求优先拆出 2~3 个子任务，既不要漏掉不同意图，也不要把同一意图拆成两步。

### 执行流程

```
用户问题「帮我对比年假和调休的区别，然后告诉我休5天需要提前几天申请」
  └─ Planner：命中多诉求关键词 → TaskDecomposer 拆解
       └─ AgentLoop 逐个执行子任务（Trace 记录 subtask_1 / subtask_2 / ...）
            ├─ 子任务 1：rag_query（检索制度）
            ├─ 子任务 2：rag_query（申请时效）
            └─ 子任务 3：calculator（算天数）
                 └─ Aggregator 汇总 → 一个完整回答（不出现「第一个子任务…」这类流水账）
```

拆解输出的格式（大模型返回后由 `TaskDecomposer._parse` 校验与截断）：

```json
[
  { "step": 1, "action": "rag_query", "params": { "question": "年假和调休的区别" }, "reason": "先检索制度" },
  { "step": 2, "action": "rag_query", "params": { "question": "年假申请提前几天" }, "reason": "确认申请时效" },
  { "step": 3, "action": "calculator", "params": { "expression": "5" }, "reason": "计算相关天数" }
]
```

### 容错设计

- **单个子任务失败**：标记为失败并继续执行剩余子任务，不会中断整个流程
- **全部子任务失败**：返回「抱歉，这个问题需要分几步处理，但执行过程中没能拿到有效结果，建议换一种问法或稍后重试。」，接口不报错
- **汇总大模型不可用**：退化为直接列出各部分结果，保证仍有可用输出
- **子任务里识别到用户偏好**：照常写入长期记忆，与单步链路一致
- 多步任务不做反思重试（`Reflector` 只作用于单步链路），避免响应时间不可控

## 配置项

全部集中在 `app/utils/config.py`：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 无（必填） | 从 `.env` 读取，缺失时启动即报错退出 |
| `LLM_MODEL` | `qwen-turbo` | 生成模型 |
| `MAX_RETRIES` | 2 | 大模型调用失败后的最大重试次数（总尝试 3 次） |
| `RETRY_DELAY` | 1 | 重试基础间隔（秒），指数退避：1 → 2 → 4 |
| `VECTOR_PERSIST_DIR` | `./data/vectors` | FAISS 索引与元数据目录 |
| `TOP_K` | 3 | 每次检索返回的条数 |
| `RAG_SCORE_THRESHOLD` | 0.30 | 最高余弦相似度低于此值即判定知识库外问题，直接拒答 |
| `MEMORY_MAX_TURNS` | 10 | 短期记忆保留的对话轮数（1 轮 = 用户 + 助手各 1 条） |
| `SUMMARY_TRIGGER_TURNS` | 15 | 达到该轮数触发摘要压缩，压缩最早的 5 轮 |
| `SESSION_CACHE_MAX_SIZE` | 100 | 会话级记忆缓存上限，超出按 LRU 淘汰 |
| `ENABLE_TASK_DECOMPOSITION` | `True` | 是否开启多步任务分解（关闭后所有问题都按单步处理） |
| `MAX_SUBTASKS` | 5 | 单个问题最多拆解的子任务数量 |
| `MCP_AUTH_TOKEN` | 空 | MCP 服务器 Bearer Token，为空时跳过鉴权（仅本地开发） |
| `EMBEDDING_MODEL` | `text-embedding-v2` | 向量化模型 |
| `EMBEDDING_DIMENSION` | 1536 | 向量维度（与 FAISS 索引一致） |
| `KNOWLEDGE_DIR` | `./data/knowledge` | 知识源文件目录 |

关于 `RAG_SCORE_THRESHOLD`：`score` 是**余弦相似度**，不是「相关概率」。实测（`text-embedding-v2` + 当前知识库）知识库内问题最高相似度约 0.39~0.77，知识库外问题（如「今天天气怎么样」）约 0.05~0.24，故取 0.30。调整阈值请先看检索日志里打印的实际分布，日志会输出最高分与阈值。

## 关键设计决策

1. **自建轻量 Agent 框架**：手写 Planner / Executor / Reflector / 工具注册表，替代 LangChain，依赖包少、行为完全可控。
2. **规则层 + 大模型双层决策**：关键词硬匹配做确定性路由（0 Token、毫秒级），大模型处理模糊意图，缓解同类政策分类混淆。
3. **RAG + 幻觉抑制**：Prompt 强制只依据参考资料回答；检索为空或最高相似度低于 `RAG_SCORE_THRESHOLD` 时直接拒答、不调用大模型，避免编造。
4. **知识库外问题统一走检索兜底**：天气、新闻这类知识库外话题交给 `rag_query`，由阈值统一拒答，而不是让 Planner 去调外部接口编造答案（Planner 提示词里显式约定了这一点）。
5. **大模型调用容错**：统一封装 `call_llm_with_retry`（`app/utils/llm.py`），指数退避重试（`MAX_RETRIES` / `RETRY_DELAY` 可配）；流式调用一旦已产出内容就不再重试（避免重复输出），改为向客户端补发兜底提示。
6. **流式输出**：`/api/v1/chat/stream` 与 `/api/v1/agent/stream` 基于 SSE 逐块下发，事件格式与响应头统一收敛在 `app/utils/sse.py`（含 `X-Accel-Buffering: no`，便于反代场景）。
7. **三层上下文管理**：短期记忆（会话内）、长期记忆（跨会话偏好落盘）、工作记忆（Trace 中的任务状态）。
8. **短期记忆摘要压缩**：对话达到 `SUMMARY_TRIGGER_TURNS`（默认 15）轮时，把最早的 5 轮交给大模型压缩成不超过 100 字的摘要，以 `role="system"` 消息放回 history 开头，再丢弃这 5 轮，使历史回到 `MEMORY_MAX_TURNS`（默认 10）轮以内；摘要生成失败则回退到直接截断并记 WARNING，不影响主流程。`llm._build_messages` 会把 `system` 角色（摘要）与 System Prompt 合并，避免被当成非 user/assistant 消息丢掉。
9. **会话级短期记忆缓存 + LRU 淘汰**：`AgentLoop` 用 `{user_id: Memory}`（`OrderedDict` + `threading.Lock`）缓存会话，使短期记忆与历史摘要能跨 HTTP 请求累积；上限 `SESSION_CACHE_MAX_SIZE`（默认 100），超出淘汰最久未使用的会话。短期记忆只存内存、服务重启即清空，长期画像仍照常落盘——这是明确的取舍。
10. **工具调度与未知动作兜底**：Executor 先按工具声明的参数签名调度；参数不全或动作未实现时回退到知识库检索，由阈值统一拒答，绝不把 `未知操作: xxx` 这类内部字符串返回给用户。
11. **长短期记忆协同回答追问**：`memory_retrieval` 同时把历史摘要和长期画像交给大模型，因此「我前面提到过什么」「我叫什么名字」在会话内可用，偏好类问题在服务重启后（短期记忆已清空）依然能从画像回答。
12. **日志兼容 Windows GBK 控制台**：控制台日志不使用 emoji，改用 `[OK]` / `[ERROR]` / `[SKIP]` / `[INFO]` / `[SEARCH]` 纯文本标记，避免 `UnicodeEncodeError`；文件日志固定 UTF-8。
13. **多步任务分解 + 汇总**：关键词先判多诉求（0 Token），命中才调用 `TaskDecomposer` 拆解；子任务由 Executor 逐个执行，`Aggregator` 负责融会贯通成一段回答。拆解失败回退单步，单个子任务失败不影响整体，全部失败则给友好提示。
14. **企业知识能力 MCP 化**：MCP 服务器只暴露企业知识相关工具（知识问答、跨文档检索、文档摘要、结构化抽取、长期记忆），不掺天气、汇率这类通用工具；通过 FastAPI `mount("/mcp")` 提供 SSE，同时支持 stdio 独立运行；`MCP_AUTH_TOKEN` 做 Bearer 鉴权，调用日志独立落盘便于审计。

## 可观测性

- 每个请求生成一个 Trace ID，日志形如 `[Trace 29709fc2] planner 开始` / `[Trace 29709fc2] 总耗时 2269.06ms`
- 多步任务会把每个子任务与汇总步骤单独打点：`subtask_1` / `subtask_2` / `aggregate`
- 控制台与文件双写，文件按日切分：`logs/app_YYYY-MM-DD.log`（UTF-8）；MCP 调用日志单独写 `logs/mcp_YYYYMMDD.log`
- Agent 响应体带 `trace_id`，可以把一次回答与全部执行步骤对齐排查

## 实测验收

**测试日期：2026-09-15**　｜　环境：Python 3.14.5 + `qwen-turbo` + `text-embedding-v2` + 知识库 12 条　｜　后端：`uvicorn app.main:app` @ `127.0.0.1:8000`

**测试方式**：真实 HTTP 请求（`requests` 直连本地服务），下表「实际结果」均为接口原始返回；相似度与耗时取自响应计时和 `logs/app_2026-09-15.log`。

### A. 基础功能回归（6/6 通过）

| # | 接口 | 输入 | 预期 | 实际结果 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| A1 | POST `/api/v1/chat` | 年假怎么申请 | 基于知识库回答年假政策 | 200，`{"answer":"根据【企业年假制度】，年假申请需要在飞书上提交，经部门经理审批。","status":"success"}`；日志 `检索相关性通过，最高分 0.6148 >= 阈值 0.3` | 1802ms |
| A2 | POST `/api/v1/chat` | 今天天气怎么样 | 阈值拦截，返回兜底话术 | 200，`{"answer":"未找到与您问题直接相关的内容，建议您换一种问法或咨询相关部门。","status":"success"}`；日志 `最高分 0.1163 < 阈值 0.3`，未调用大模型 | 684ms |
| A3 | POST `/api/v1/agent` | 你好（user_id=test_1） | `action = direct_response` | 200，`action = "direct_response"`，回答「您好，我是您的智能助手。如果您有公司政策、流程或制度方面的问题，可以随时问我。」 | 1173ms |
| A4 | POST `/api/v1/agent` | 帮我算 128*7（user_id=test_1） | `calculator`，返回 896 | 200，`action = "calculator"`，回答「计算结果: 128*7 = 896」 | 1244ms |
| A5 | POST `/api/v1/agent` | 我喜欢喝冰咖啡（user_id=test_2） | 记入长期偏好 | 200，`action = "memory_retrieval"`，回答「已记录您的偏好: {'general': '喝冰咖啡'}」（与规则层命中偏好关键词一致） | 116ms |
| A6 | POST `/api/v1/agent` | 你记得我喜欢喝什么吗（user_id=test_2） | 回答含「冰咖啡」 | 200，`action = "memory_retrieval"`，回答「根据之前的对话，您喜欢喝冰咖啡。」 | 4039ms |

### B. 多步任务分解（通过）

- 输入：`帮我对比年假和调休的区别，然后告诉我休5天需要提前几天申请`（user_id=fix_check）
- 实际：200，`action = "multi_step"`，`reasoning = "问题包含多个诉求，已拆解为 2 个子任务依次执行"`，总耗时 **6922ms**（Trace `6561952e`）
- 拆解结果（无重复、无非法参数）：

| 步骤 | Planner 拆解出的子任务 | 检索最高分 | 耗时 | 结果 |
| --- | --- | --- | --- | --- |
| subtask_1 | `rag_query`：年假和调休的区别 | 0.6461 | 1815ms | 成功，给出年假规则 |
| subtask_2 | `rag_query`：休5天年假需要提前几天申请 | 0.6576 | 1852ms | 成功，如实说明资料未提及申请天数 |
| aggregate | 汇总生成最终回答 | — | 1514ms | 成功 |

完整回答（接口原始返回原文）：

> 根据现有资料，年假是员工在入职满一定年限后享有的带薪假期，具体来说，入职满1年的员工享有5天带薪年假。但资料中未明确说明休5天年假需要提前几天申请。同时，调休的具体定义或规定在提供的资料中未提及。

结论：

- 拆成 2 个子任务、无重复，且第二个子任务的问题保留了关键限定词「年假」；本次没有出现 `calculator` 子任务，因此不存在「把中文句子当算式」的问题
- 最终回答里没有任何知识库中不存在的内容：调休、以及申请天数都如实标注「资料中未提及」。修复前同一问题会答出「调休通常是指因加班而获得的休息时间」，这句话在 12 条知识里并不存在
- 仍有一处**检索召回**问题（非本次修复范围）：知识库 `policy.md` 明确写了「年假需要提前 3 个工作日申请」，但子任务 2 的 top-3 检索没有命中该条，回答因此保守地说「未明确说明」。详见「已知限制」

### C. MCP 服务器

| 检查项 | 结果 |
| --- | --- |
| `GET /mcp` 信息页 | 200，返回 `{"server": "智核 · 企业知识 MCP 中枢", "transport": "sse", "sse_endpoint": "/mcp/sse", "messages_endpoint": "/mcp/messages/", "auth": "未启用（本地开发模式）", "tools": ["rag_query", "multi_doc_search", "summarize_document", "extract_structured", "memory_retrieval"]}`，端点可访问 |
| 5 个工具已注册 | 是，工具名与 `/mcp` 返回一致 |
| 鉴权状态 | 未启用（本地开发模式），与本机 `.env` 未配置 `MCP_AUTH_TOKEN` 一致 |
| 通过 MCP 客户端调用 5 个工具 | **待验证**：本轮未执行（`mcp dev app/mcp_server.py` 是交互式 Inspector，无法无人值守跑完） |
| `logs/mcp_YYYYMMDD.log` | 存在：`logs/mcp_20260915.log`，记录了 5 个工具的调用（工具名、参数、耗时、返回长度），最后写入 2026-09-15 06:52；本轮只访问了信息页，未产生新的工具调用日志 |

### D. 流式输出（通过）

- 输入：`POST /api/v1/agent/stream {"question": "年假怎么申请", "user_id": "test_4"}`
- 状态码 200，`Content-Type: text/event-stream; charset=utf-8`
- 首块到达 **1731.6ms**，共 **20 块**，`data: [DONE]` 在 **2182.7ms** 收尾
- 事件片段（原文摘录）：

```
  [   1732ms] +2字 '根据'
  [   1732ms] +2字 '企业'
  [   1735ms] +1字 '年'
  [   1741ms] +1字 '假'
  [   1792ms] +6字 '制度，入职满'
  ...
  [   2123ms] +7字 '提交，并经部门'
  [   2147ms] +5字 '经理审批。'
  [   2183ms] data: [DONE]
```

- 拼出的完整回答：`根据企业年假制度，入职满1年的员工享有5天带薪年假，入职满3年的员工享有10天带薪年假。年假可以累积到次年3月，过期作废。年假申请需要在飞书上提交，并经部门经理审批。`

### 本轮未覆盖（待验证，不作为通过结论）

- **大模型断网降级**：本轮 Key 与网络均正常，没有复现断网场景；重试与降级代码路径本轮只走通了正常分支。
- **短期记忆摘要压缩**：本轮对话轮数没有达到 `SUMMARY_TRIGGER_TURNS`（15 轮），日志中无「历史对话已压缩」记录。
- **多步任务全部子任务失败**：本轮 5 个子任务中 1 失败 1 回退、3 成功，未覆盖「全部失败」分支。
- **MCP 客户端端到端调用 5 个工具**：见 C 节。
- **开启 `MCP_AUTH_TOKEN` 的鉴权拦截**：本轮为开发模式（未配置 Token）。

## 常见问题与排错

| 现象 | 原因与处理 |
| --- | --- |
| 启动直接退出，打印 `[ERROR] 配置错误: 请在 .env 文件中配置 DASHSCOPE_API_KEY` | 根目录没有 `.env`，或变量名写错。参照 `.env.example` 补上即可 |
| 提问返回「当前服务繁忙，请稍后重试。」 | DashScope Key 无效 / 过期 / 欠费，或网络不通。日志里会有两条重试 WARNING 与具体错误（如 `401 InvalidApiKey`），先到百炼控制台确认 Key |
| 提问总是返回「未找到与您问题直接相关的内容…」 | 一是知识库没构建（先跑 `python build_knowledge_base.py`）；二是阈值偏高，看日志里打印的最高分，再调 `RAG_SCORE_THRESHOLD` |
| 控制台报 `UnicodeEncodeError: 'gbk' codec can't encode character` | 日志里又出现了 emoji。项目约定日志只用 `[OK]` / `[ERROR]` / `[SKIP]` / `[INFO]` / `[SEARCH]` 纯文本标记，新加日志请沿用；也可执行 `chcp 65001` 切到 UTF-8 控制台 |
| 前端提示「服务连接失败，请确认后端已启动」 | 后端没起、端口不是 8000，或前端不是从 `5173` 访问（CORS 只放行该来源） |
| MCP 客户端连不上，服务端返回 401 | `.env` 里配了 `MCP_AUTH_TOKEN`，客户端却没带 `Authorization: Bearer <token>`；打开 `GET /mcp` 信息页可确认当前鉴权状态 |
| 端口被占用 | `uvicorn app.main:app --port 8001`，同时把前端里的后端地址改成 8001 |

## 已知限制与后续优化

- **短期记忆只在内存**：服务重启后会话上下文清空（长期画像不受影响）。如需跨重启续聊，可把 short_term 持久化到 `data/memory/sessions/<user_id>.json`。
- **删除知识走全量重建**：`DELETE /api/v1/admin/knowledge/delete/{doc_id}` 会清空并重建整个索引，条目多时较慢，可换成按 id 重建或软删除。
- **规则层关键词硬编码**：新增业务词需改 `app/core/rules.py`，可改为配置化或从知识库自动生成。
- **`http_request` / `calculator` 依赖 Planner 给出参数**：参数不全时回退到知识库检索；`http_request` 未做 URL 白名单与结果摘要，用于演示工具调用链路。
- **`pypdf` / `python-multipart` 目前未被引用**：为后续 PDF 知识上传预留，未使用可移除。
- **知识库规模小**：当前 12 条、单文件切段，检索阈值基于这个分布实测，扩大知识库后建议重新校准 `RAG_SCORE_THRESHOLD`，并考虑引入 BM25 混合检索 + rerank。
- **多步任务不流式逐字下发**：汇总结果一次性返回（首字等待时间 = 各子任务耗时之和），如需逐字可把 `Aggregator` 换成 `call_llm_stream`。
- **多步任务不做反思重试**：`Reflector` 仅作用于单步链路，多步链路的纠错依赖单个子任务自身的兜底逻辑。
- **多步子任务的检索召回**：子任务被拆细后，`params.question` 会变短，可能召回不到原本能命中的条目（例如「休5天年假需要提前几天申请」没有命中 `policy.md` 里的「年假需要提前 3 个工作日申请」）。可考虑提高 `TOP_K`，或在拆解时把原问题作为检索上下文一起带上。
- **MCP 文档粒度依赖 `source` 字段**：`summarize_document` 以知识条目的 `source` 作为文档名，导入知识时建议保持命名规范。

## 说明

本项目为个人独立开发的工程化 Agent 系统，用于学习与面试演示。所有代码可完整运行，README 中的相似度、耗时等数值均来自本机实测。
