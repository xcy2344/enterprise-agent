from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.agent_loop import AgentLoop
from app.utils.logger import logger

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