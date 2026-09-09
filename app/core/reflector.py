from typing import Dict, Any, List
from app.utils.logger import logger
import json


class Reflector:
    """
    反思器：检查执行结果，判断是否需要修正
    """

    def __init__(self):
        self.max_retries = 2

    def reflect(
        self,
        user_input: str,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        memory_context: List[Dict],
        user_profile: Dict = None
    ) -> Dict[str, Any]:
        """
        反思执行结果，决定是否需要修正

        返回：
        {
            "need_retry": True/False,
            "new_plan": {...},  # 如果需要重试，新的计划
            "feedback": "反思反馈"
        }
        """
        action = plan.get("action", "")
        success = result.get("success", False)
        answer = result.get("result", "")

        # 情况1：执行失败 → 重试
        if not success:
            logger.warning(f"执行失败，准备重试: {result}")
            return {
                "need_retry": True,
                "new_plan": {
                    "action": "direct_response",
                    "params": {"question": user_input},
                    "reasoning": "执行失败，降级为直接回复"
                },
                "feedback": "工具执行失败，已降级处理"
            }

        # 情况2：用户表达了偏好，但没有被存储
        # 检查用户输入是否包含偏好关键词
        preference_keywords = ["喜欢", "不喜欢", "爱", "讨厌", "偏好", "习惯", "希望", "想要"]
        if any(kw in user_input for kw in preference_keywords):
            # 检查是否已经存储了偏好
            stored_prefs = user_profile.get("preferences", {}) if user_profile else {}
            # 简单检查：如果回答中没有提到"已记录"或"已记住"，说明可能没存储
            if "已记录" not in answer and "已记住" not in answer and "已保存" not in answer:
                logger.info("检测到用户偏好未存储，触发记忆更新")
                return {
                    "need_retry": True,
                    "new_plan": {
                        "action": "memory_retrieval",
                        "params": {"question": user_input},
                        "reasoning": "用户表达了偏好，需要存储到记忆中"
                    },
                    "feedback": "检测到用户偏好，已触发记忆存储"
                }

        # 情况3：直接回答中没有回答问题（检测到回答太短或过于通用）
        if action == "direct_response" and len(answer) < 20:
            # 尝试用 RAG 再回答一次
            return {
                "need_retry": True,
                "new_plan": {
                    "action": "rag_query",
                    "params": {"question": user_input},
                    "reasoning": "直接回答不充分，尝试使用 RAG 检索"
                },
                "feedback": "直接回答不充分，已切换到 RAG 模式"
            }

        # 情况4：正常，不需要修正
        return {
            "need_retry": False,
            "new_plan": None,
            "feedback": "执行成功，无需修正"
        }