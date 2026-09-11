# 企业智能助手 Agent 系统

一个面向企业场景的轻量级 Agent 系统。员工通过自然语言查询公司政策，系统自主完成意图识别、工具调用、知识检索和回答生成，并具备跨会话记忆能力。

## 技术栈

- 语言：Python 3.11+
- 后端：FastAPI + Uvicorn
- 大模型：通义千问（DashScope API）
- 向量检索：FAISS + 百炼 text-embedding-v2
- Agent 架构：自建 Planner-Executor-Reflector 框架（ReAct 模式）
- 数据存储：FAISS 向量索引 + JSON 用户画像
- 工程化：分层架构、环境配置隔离、全链路 Trace ID 可观测

## 项目结构
enterprise-agent/
├── app/
│ ├── api/ # 接口层：路由定义，不含业务逻辑
│ ├── core/ # 业务层：Planner/Executor/Reflector/Memory/Agent Loop
│ ├── tools/ # 工具层：RAG 工具注册表，可扩展
│ ├── utils/ # 基础层：配置/日志/Embedding/可观测
│ └── main.py # 服务入口
├── data/
│ ├── knowledge/ # 知识文档
│ ├── memory/ # 用户画像持久化
│ └── vectors/ # FAISS 向量索引
├── requirements.txt
└── README.md

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
python build_knowledge_base.py
uvicorn app.main:app --reload
API 接口
接口	方法	说明
/api/v1/chat	POST	基础对话（纯 RAG 问答）
/api/v1/agent	POST	完整 Agent 对话（含规划、工具调用、记忆）
/api/v1/admin/knowledge/add	POST	增量添加知识
/api/v1/admin/knowledge/list	GET	查看知识库列表
/health	GET	健康检查
架构设计
分层架构
API 层（FastAPI）：仅负责路由和参数校验，不包含业务逻辑

业务层（Core）：Planner 意图识别、Executor 工具执行、Reflector 结果修正、Memory 记忆管理、Agent Loop 核心循环

基础层（Infra）：配置管理、日志系统、向量存储、Embedding 封装，面向接口设计，替换底层不影响上层

关键设计决策
自建轻量级 Agent 框架：手写 Planner/Executor/Reflector/Tool 注册表，替代 LangChain 依赖，依赖包从 30+ 减少到 5 个，完全掌控系统行为。

规则层 + 大模型双层决策：关键词硬匹配做确定性路由（0 Token 消耗），大模型处理模糊意图，解决同类政策分类混淆问题。

RAG + 幻觉抑制：System Prompt 强制约束回答必须基于参考资料，检索为空时直接拒绝回答。

三层上下文管理：短期记忆（会话内）、长期记忆（跨会话用户偏好）、工作记忆（任务状态）。

可观测性：全链路 Trace ID 追踪，记录 Planner → Executor → Reflector 每一步的输入、输出和耗时。

说明
本项目为个人独立开发的工程化 Agent 系统，用于学习与面试演示。所有代码已开源，可完整运行。