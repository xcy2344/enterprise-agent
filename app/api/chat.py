from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.rag import rag_service
from app.utils.logger import logger

# 创建路由
router = APIRouter()


# 定义请求体格式
class ChatRequest(BaseModel):
    question: str


# 定义响应体格式
class ChatResponse(BaseModel):
    answer: str
    status: str


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    对话接口：接收用户问题，返回 AI 回答
    """
    try:
        logger.info(f"收到请求: {request.question}")
        answer = rag_service.answer(request.question)
        return ChatResponse(answer=answer, status="success")
    except Exception as e:
        logger.error(f"处理失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误")