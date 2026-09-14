from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.rag import rag_service
from app.utils.logger import logger
from app.utils.sse import SSE_HEADERS, SSE_MEDIA_TYPE, sse_stream

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


@router.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """
    流式对话接口（SSE）：检索到大模型逐块生成，边生成边返回

    事件格式：data: {"content": "文本增量"}，结束时发送 data: [DONE]
    用同步生成器 + StreamingResponse，Starlette 会在线程池中迭代，不阻塞事件循环
    """
    logger.info(f"收到流式请求: {request.question}")
    return StreamingResponse(
        sse_stream(rag_service.answer_stream(request.question)),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS
    )
