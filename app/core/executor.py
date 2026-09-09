from typing import Dict, Any
from app.tools import get_tool
from app.utils.logger import logger
import re


class Executor:
    """执行器：执行 Planner 的决策"""

    def execute(self, plan: Dict[str, Any], user_profile: Dict = None) -> Dict[str, Any]:
        action = plan.get("action")
        params = plan.get("params", {})
        reasoning = plan.get("reasoning", "")

        logger.info(f"执行计划: action={action}, params={params}")

        if action == "rag_query":
            question = params.get("question", "")
            if not question:
                return {"success": False, "result": "缺少问题参数", "action": action}
            tool = get_tool("rag_query")
            if not tool:
                return {"success": False, "result": "RAG 工具不可用", "action": action}
            try:
                result = tool.execute(question=question)
                return {"success": True, "result": result.get("result", "查询无结果"), "action": action}
            except Exception as e:
                logger.error(f"RAG 工具执行失败: {e}")
                return {"success": False, "result": f"查询失败: {e}", "action": action}

        elif action == "memory_retrieval":
            user_input = params.get("question", "")

            # 先检查：用户是在问"你记得吗"还是真的在表达新偏好
            retrieval_keywords = ["记得", "还记得", "知道", "记住", "记得我", "你记得"]
            is_retrieval_request = any(kw in user_input for kw in retrieval_keywords)

            # 如果用户是在问"你记得吗"，直接从已有画像中检索
            if is_retrieval_request:
                if user_profile:
                    stored_prefs = user_profile.get("preferences", {})
                    if stored_prefs:
                        reply = "从记忆中检索到您的偏好：\n"
                        for key, value in stored_prefs.items():
                            reply += f"- {key}: {value}\n"
                        return {"success": True, "result": reply, "action": action}
                    else:
                        return {"success": True, "result": "我没有您的偏好记录，您可以告诉我一些关于您的信息。", "action": action}
                else:
                    return {"success": True, "result": "用户画像不存在", "action": action}

            # 如果用户是在表达新偏好，提取并存储
            preferences = {}
            patterns = [
                (r"(?:我喜欢|我爱|我偏好|我习惯)\s*(.+)", "general"),
                (r"(?:我不喜欢|我讨厌)\s*(.+)", "dislike"),
            ]
            for pattern, category in patterns:
                match = re.search(pattern, user_input)
                if match:
                    pref_value = match.group(1).strip()
                    if pref_value:
                        preferences[category] = pref_value
                        logger.info(f"从用户输入提取偏好: {category} = {pref_value}")
                        break

            if preferences and user_profile is not None:
                return {
                    "success": True,
                    "result": f"已记录您的偏好: {preferences}",
                    "action": action,
                    "need_save": True,
                    "preferences": preferences
                }

            # 如果没有提取到偏好，返回提示
            return {"success": True, "result": "我没有您的偏好记录，您可以告诉我一些关于您的信息。", "action": action}

        elif action == "direct_response":
            return {
                "success": True,
                "result": "您好，我是您的智能助手。如果您有公司政策、流程或制度方面的问题，可以随时问我。",
                "action": action
            }

        elif action == "clarify":
            return {
                "success": True,
                "result": "抱歉，我没完全理解您的问题。能否再具体一点告诉我您想了解什么？",
                "action": action
            }

        else:
            return {"success": False, "result": f"未知操作: {action}", "action": action}