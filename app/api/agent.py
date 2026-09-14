from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.core.agent_loop import AgentLoop
from app.utils.logger import logger
from app.utils.sse import SSE_HEADERS, SSE_MEDIA_TYPE, sse_stream

router = APIRouter()
agent = AgentLoop()


class AgentRequest(BaseModel):
    question: str
    user_id: str = "default_user"


class AgentResponse(BaseModel):
    success: bool
    answer: str
    action: str
    reasoning: str


@router.post("/agent", response_model=AgentResponse)
async def agent_chat(request: AgentRequest):
    """Agent 对话接口"""
    try:
        logger.info(f"收到 Agent 请求: user_id={request.user_id}")
        result = agent.run(request.question, request.user_id)
        return AgentResponse(
            success=result["success"],
            answer=result["answer"],
            action=result["action"],
            reasoning=result["reasoning"]
        )
    except Exception as e:
        logger.error(f"Agent 处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/stream")
def agent_chat_stream(request: AgentRequest):
    """
    Agent 流式对话接口（SSE）：rag_query 走流式生成，其他意图一次性返回

    事件格式：data: {"content": "文本增量"}，结束时发送 data: [DONE]
    """
    logger.info(f"收到 Agent 流式请求: user_id={request.user_id}")
    return StreamingResponse(
        sse_stream(agent.run_stream(request.question, request.user_id)),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS
    )
