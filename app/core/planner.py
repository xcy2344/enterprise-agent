import json
from typing import Dict, Any, List
from app.tools import list_tools
from app.utils.logger import logger
from app.core.rules import rule_layer
import dashscope
from dashscope import Generation
from app.utils.config import Config


class Planner:
    """任务规划器：分析用户意图，决定调用哪个工具"""

    def __init__(self):
        self.model = Config.LLM_MODEL

    def plan(self, user_input: str, memory_context: List[Dict], user_profile: Dict = None) -> Dict[str, Any]:
        """
        根据用户输入、对话历史和用户画像，生成执行计划

        返回格式：
        {
            "action": "rag_query" | "direct_response" | "clarify" | "memory_retrieval",
            "params": {"question": "用户问题"},
            "reasoning": "选择这个工具的原因"
        }
        """
        # ===== 第一步：先走规则层（精确匹配，不走大模型）=====
        rule_result = rule_layer.match(user_input)
        if rule_result:
            logger.info(f"规则层命中，跳过 Planner: {rule_result}")
            return rule_result

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

        prompt = f"""
你是一个任务规划器。根据用户的问题、对话历史和用户画像，决定下一步该做什么。

可用工具：
{tools_desc}

对话历史：
{memory_context}

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
2. 如果用户问的是关于自己的偏好或之前说过的话，使用 memory_retrieval
   - 例如：你记得我喜欢喝什么吗、我喜欢什么
3. 如果是普通问候或无关话题，使用 direct_response
   - 例如：你好、你是谁、再见
4. 如果问题不明确，使用 clarify
"""

        try:
            response = Generation.call(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                result_format="message"
            )
            result = response.output.choices[0].message.content
            logger.info(f"Planner 原始返回: {result}")

            # 尝试解析 JSON
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                return json.loads(result[json_start:json_end])
            else:
                logger.warning(f"Planner 返回非 JSON 格式: {result}")
                return {"action": "direct_response", "params": {}, "reasoning": "无法解析，直接回复"}

        except Exception as e:
            logger.error(f"规划器调用失败: {e}")
            return {"action": "direct_response", "params": {}, "reasoning": f"出错: {e}"}