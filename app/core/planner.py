import json
from typing import Dict, Any, List, Optional
from app.tools import list_tools
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger
from app.core.rules import rule_layer
from app.core.task_decomposer import TaskDecomposer
from app.utils.config import Config


class Planner:
    """任务规划器：分析用户意图，决定调用哪个工具"""

    def __init__(self):
        self.model = Config.LLM_MODEL
        self.decomposer = TaskDecomposer()

    def plan(self, user_input: str, memory_context: List[Dict], user_profile: Dict = None) -> Optional[Dict[str, Any]]:
        """
        根据用户输入、对话历史和用户画像，生成执行计划

        大模型不可用（重试后仍失败）时返回 None，由上层做降级处理

        返回格式（单步）：
        {
            "mode": "single_step",
            "action": "rag_query" | "direct_response" | "clarify" | "memory_retrieval",
            "params": {"question": "用户问题"},
            "reasoning": "选择这个工具的原因"
        }

        返回格式（多步，Config.ENABLE_TASK_DECOMPOSITION 开启且问题包含多个诉求）：
        {
            "mode": "multi_step",
            "subtasks": [{"step": 1, "action": "工具名", "params": {...}, "reason": "..."}],
            "reasoning": "拆解原因"
        }
        """
        # ===== 第零步：多诉求问题先做任务分解 =====
        if TaskDecomposer.needs_decomposition(user_input):
            subtasks = self.decomposer.decompose(user_input, memory_context)
            if subtasks:
                logger.info(f"Planner 判定为多步任务，拆解出 {len(subtasks)} 个子任务: {subtasks}")
                return {
                    "mode": "multi_step",
                    "subtasks": subtasks,
                    "params": {"question": user_input},
                    "reasoning": f"问题包含多个诉求，已拆解为 {len(subtasks)} 个子任务依次执行"
                }
            logger.warning("任务分解未成功，回退到单步规划")

        # ===== 第一步：先走规则层（精确匹配，不走大模型）=====
        rule_result = rule_layer.match(user_input)
        if rule_result:
            logger.info(f"规则层命中，跳过 Planner: {rule_result}")
            return {**rule_result, "mode": "single_step"}

        # ===== 第二步：规则层未命中，走大模型判断 =====
        tools = list_tools()
        tools_desc = "\n".join([f"- {t['name']}: {t['description']}" for t in tools])

        # 构建用户画像描述
        profile_desc = "暂无用户画像"
        if user_profile:
            profile_desc = f"""
用户偏好：{user_profile.get('preferences', {})}
历史查询：{user_profile.get('history_queries', [])[-5:]}
"""

        # 构建对话历史描述（含 role="system" 的历史摘要）
        history_desc = self._format_history(memory_context)

        prompt = f"""
你是一个任务规划器。根据用户的问题、对话历史和用户画像，决定下一步该做什么。

可用工具：
{tools_desc}

对话历史：
{history_desc}

用户画像：
{profile_desc}

用户最新问题：{user_input}

请返回 JSON 格式的决策：
{{
    "action": "rag_query" 或 "direct_response" 或 "clarify" 或 "memory_retrieval",
    "params": {{"question": "用户问题"}},
    "reasoning": "选择这个工具的原因"
}}

规则：
1. 如果用户询问公司内部事务（政策、流程、制度），使用 rag_query
   - 例如：年假、加班、报销、考勤、入职、培训、出差、福利、社保、公积金
2. 如果用户问的是公司知识库之外的话题（如今天天气怎么样、最新新闻、通用知识），同样使用 rag_query
   - 检索不到相关内容时系统会统一拒答，不要编造答案，也不要改用 http_request
3. 如果用户问的是关于自己的个人身份、偏好，或之前说过的话，使用 memory_retrieval
   - 例如：我叫什么名字、我是谁、我的名字是什么、你知道我是谁吗、你记得我喜欢喝什么吗、我喜欢什么
4. 如果是普通问候或闲聊，使用 direct_response
   - 例如：你好、你是谁、再见
   - 注意区分：问助手自己的身份（你是谁）走 direct_response；问用户本人身份（我是谁、我叫什么名字）走 memory_retrieval
5. 如果问题不明确，使用 clarify
"""

        # 调用大模型（内部含重试与指数退避）
        result = call_llm_with_retry(prompt=prompt, model=self.model)

        # 大模型不可用：返回 None，由 AgentLoop 返回降级回答
        if result is None:
            logger.error("Planner 大模型调用失败，返回 None 触发降级")
            return None

        logger.info(f"Planner 原始返回: {result}")

        # 尝试解析 JSON
        json_start = result.find('{')
        json_end = result.rfind('}') + 1
        if json_start == -1 or json_end <= json_start:
            logger.warning(f"Planner 返回非 JSON 格式: {result}")
            return {"mode": "single_step", "action": "direct_response", "params": {}, "reasoning": "无法解析，直接回复"}

        try:
            plan = json.loads(result[json_start:json_end])
            plan.setdefault("mode", "single_step")
            return plan
        except ValueError as e:
            logger.warning(f"Planner 返回 JSON 解析失败: {e}")
            return {"mode": "single_step", "action": "direct_response", "params": {}, "reasoning": "无法解析，直接回复"}

    @staticmethod
    def _format_history(memory_context: List[Dict]) -> str:
        """
        把记忆中的对话历史格式化成可读文本

        role="system" 的历史摘要会被明确标注，保证摘要能完整传给大模型，
        而不是以原始 dict 的形式混在提示词里。
        """
        if not memory_context:
            return "暂无对话历史"

        lines = []
        for message in memory_context:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                lines.append(f"[历史摘要] {content}")
            elif role == "user":
                lines.append(f"用户：{content}")
            else:
                lines.append(f"助手：{content}")
        return "\n".join(lines)
