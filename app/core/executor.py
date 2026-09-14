from typing import Dict, Any, List, Optional
from app.tools import get_tool
from app.core.rag import NO_RELEVANT_CONTENT_REPLY
from app.utils.config import Config
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger
import re


class Executor:
    """执行器：执行 Planner 的决策"""

    def execute(
        self,
        plan: Dict[str, Any],
        user_profile: Dict = None,
        memory_context: List[Dict] = None
    ) -> Dict[str, Any]:
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
                result = tool.execute(question=question, memory_context=memory_context)
                return {"success": True, "result": result.get("result", "查询无结果"), "action": action}
            except Exception as e:
                logger.error(f"RAG 工具执行失败: {e}")
                return {"success": False, "result": f"查询失败: {e}", "action": action}

        elif action == "memory_retrieval":
            user_input = params.get("question", "")

            # 先检查：用户是在问"你记得吗"还是真的在表达新偏好
            retrieval_keywords = [
                "记得", "还记得", "知道", "记住", "记得我", "你记得",
                "我叫什么", "我是谁", "我的名字", "你知道我是谁",
            ]
            is_retrieval_request = any(kw in user_input for kw in retrieval_keywords)

            # 询问此前对话内容（如"我前面提到过什么"）：优先基于对话记忆（含历史摘要）回答
            history_keywords = ["前面", "之前", "刚才", "提到过", "说过", "上文", "历史"]
            is_history_question = is_retrieval_request or (
                any(kw in user_input for kw in history_keywords)
                and any(marker in user_input for marker in ["什么", "哪些", "吗", "？", "?"])
            )
            if is_history_question:
                memory_answer = self._answer_from_memory(user_input, memory_context, user_profile)
                if memory_answer:
                    return {"success": True, "result": memory_answer, "action": action}
                # 大模型不可用或没有可用的历史记录：不编造，直接提示（"你记得…"继续走画像检索）
                if not is_retrieval_request:
                    return {"success": True, "result": "我没有找到相关的历史记录，您可以提供更多线索。", "action": action}

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
            # Planner 可能给出注册工具名（如 calculator / http_request），也可能是未实现的动作
            # 1) 参数满足工具声明时，按工具注册表直接调度
            tool = get_tool(action)
            if tool:
                # Planner 可能把参数塞进 question（如"帮我算一下 128*7"），
                # 对 calculator 做一次表达式提取兜底，让内置工具真正可用
                if action == "calculator" and "expression" not in params:
                    expression = self._extract_expression(
                        params.get("question") or self._latest_user_message(memory_context)
                    )
                    if expression:
                        logger.info(f"从用户输入提取到计算表达式: {expression}")
                        params = {**params, "expression": expression}
                # P2：calculator 的 expression 只接受纯数学表达式，调用前先做格式校验，
                # 命中非法字符（如中文）时直接返回失败，避免把无效参数交给工具后再报错
                if action == "calculator" and not self._is_valid_expression(
                    params.get("expression", "")
                ):
                    logger.warning(f"calculator 参数格式错误，已拦截: {params.get('expression')!r}")
                    return {"success": False, "result": "参数格式错误", "action": action}
                kwargs = {
                    key: params[key]
                    for key in tool.parameters.get("properties", {})
                    if key in params
                }
                missing = [k for k in tool.parameters.get("required", []) if k not in kwargs]
                if not missing:
                    try:
                        tool_result = tool.execute(**kwargs)
                        return {
                            "success": tool_result.get("success", False),
                            "result": tool_result.get("result", "工具无返回"),
                            "action": action
                        }
                    except Exception as e:
                        logger.error(f"工具 {action} 执行失败: {e}")
                else:
                    logger.warning(f"工具 {action} 缺少必需参数 {missing}，回退到知识库检索")

            # 2) 动作未实现或参数不全：回退到知识库检索，由相似度阈值统一拒答，
            #    避免把「未知操作: xxx」这类内部信息直接返回给用户
            question = params.get("question") or self._latest_user_message(memory_context)
            rag_tool = get_tool("rag_query")
            if question and rag_tool:
                logger.warning(f"动作 {action} 无法执行（参数不全或未实现），回退到知识库检索: {question}")
                try:
                    rag_result = rag_tool.execute(question=question, memory_context=memory_context)
                    return {"success": True, "result": rag_result.get("result", "查询无结果"), "action": "rag_query"}
                except Exception as e:
                    logger.error(f"回退知识库检索失败: {e}")

            logger.warning(f"无法执行的动作: {action}，返回兜底提示")
            return {"success": True, "result": NO_RELEVANT_CONTENT_REPLY, "action": action}

    @staticmethod
    def _extract_expression(text: str) -> str:
        """
        从自然语言中提取数学表达式（如"帮我算一下 128*7" -> "128*7"）

        仅在 Planner 选择了 calculator 但没有给出 expression 时使用。
        """
        if not text:
            return ""
        match = re.search(r"[-+]?\d[\d\s.+\-*/()%]*\d", text)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _is_valid_expression(expression: str) -> bool:
        """
        校验 calculator 的 expression 是否为纯数学表达式（P2）

        只允许数字、+ - * / ( ) . 和空格；包含中文等其他字符时返回 False，
        由调用方直接返回「参数格式错误」，避免无效调用。
        """
        if not expression or not expression.strip():
            return False
        return re.fullmatch(r"[\d+\-*/().\s]+", expression) is not None

    @staticmethod
    def _latest_user_message(memory_context: List[Dict] = None) -> str:
        """
        取对话记忆中最新的一条用户消息

        用于动作无法执行时定位用户问题：AgentLoop 在规划前已把本轮问题写入记忆，
        因此这里能拿到用户原话。
        """
        if not memory_context:
            return ""
        for message in reversed(memory_context):
            if message.get("role") == "user" and message.get("content"):
                return message["content"]
        return ""
    def _answer_from_memory(
        self,
        question: str,
        memory_context: List[Dict] = None,
        user_profile: Dict = None
    ) -> Optional[str]:
        """
        基于对话记忆（含 role="system" 的历史摘要）和长期用户画像，让大模型回答相关提问

        仅在确实存在历史记录（历史摘要，或不止一轮对话）时启用；
        长期画像一并传入，避免服务重启后短期记忆清空时答不出跨会话的偏好；
        大模型不可用时返回 None，由上层回退到原来的画像检索逻辑。
        """
        if not memory_context:
            return None

        conversation = [m for m in memory_context if m.get("role") != "system"]
        has_summary = any(
            m.get("role") == "system" and m.get("content") for m in memory_context
        )
        if not has_summary and len(conversation) <= 1:
            return None

        system_prompt = """你在回答用户关于此前对话或用户本人信息的提问。
只根据【对话历史】和【用户画像】回答，不要编造；如果两者都没有相关信息，就回答“我没有找到相关的历史记录”。"""

        # 长期画像（跨会话的偏好）也一并给大模型，短期记忆清空后仍能回答“你记得我…吗”
        if user_profile:
            preferences = user_profile.get("preferences") or {}
            if preferences:
                system_prompt += f"\n\n【用户画像】\n用户偏好：{preferences}"

        return call_llm_with_retry(
            prompt=question,
            model=Config.LLM_MODEL,
            system_prompt=system_prompt,
            history=memory_context
        )
