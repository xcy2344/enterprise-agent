from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router as chat_router
from app.api.agent import router as agent_router
from app.admin.knowledge import router as knowledge_router
from app.mcp_server import build_mcp_asgi_app
from app.utils.config import Config
from app.utils.logger import logger

# 验证配置
try:
    Config.validate()
    logger.info("[OK] 配置验证通过")
except ValueError as e:
    logger.error(f"[ERROR] 配置错误: {e}")
    exit(1)

# 创建 FastAPI 应用
app = FastAPI(
    title="智核 · 企业知识 MCP 中枢",
    description="基于 RAG 的企业内部知识库问答系统 + Agent 智能体",
    version="1.0.0"
)

# 跨域配置：允许本地 Vite 前端（http://localhost:5173）访问后端接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1/admin")

# 挂载 MCP 服务器：把企业知识能力以 MCP 协议标准化暴露
# GET /mcp 为服务信息页；/mcp/sse 为 SSE 通道，供 Claude Desktop、Cursor 等客户端连接
app.mount("/mcp", build_mcp_asgi_app())


@app.get("/")
async def root():
    return {"message": "智核 · 企业知识 MCP 中枢 已启动", "status": "running"}


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}
