from fastapi import FastAPI
from app.api.chat import router as chat_router
from app.api.agent import router as agent_router
from app.admin.knowledge import router as knowledge_router
from app.utils.config import Config
from app.utils.logger import logger

# 验证配置
try:
    Config.validate()
    logger.info("✅ 配置验证通过")
except ValueError as e:
    logger.error(f"❌ 配置错误: {e}")
    exit(1)

# 创建 FastAPI 应用
app = FastAPI(
    title="企业智能客服助手",
    description="基于 RAG 的企业内部知识库问答系统 + Agent 智能体",
    version="1.0.0"
)

# 注册路由
app.include_router(chat_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1/admin")


@app.get("/")
async def root():
    return {"message": "企业智能客服助手已启动", "status": "running"}


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}