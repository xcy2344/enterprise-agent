from typing import Optional, Dict, Any
from app.utils.logger import logger


class RuleLayer:
    """
    规则层：在 Planner 之前做关键词精确匹配
    硬匹配，不走大模型，100% 确定
    """

    # 关键词 → 动作映射
    KEYWORD_RULES: Dict[str, Dict[str, Any]] = {
        # 加班相关
        "加班": {"action": "rag_query", "params": {"question": "加班政策"}},
        "加班费": {"action": "rag_query", "params": {"question": "加班费计算"}},
        "加班工资": {"action": "rag_query", "params": {"question": "加班工资"}},
        # 年假相关
        "年假": {"action": "rag_query", "params": {"question": "年假政策"}},
        "年假申请": {"action": "rag_query", "params": {"question": "年假申请流程"}},
        # 报销相关
        "报销": {"action": "rag_query", "params": {"question": "报销流程"}},
        # 考勤相关
        "考勤": {"action": "rag_query", "params": {"question": "考勤制度"}},
        "迟到": {"action": "rag_query", "params": {"question": "迟到考勤"}},
        # 入职相关
        "入职": {"action": "rag_query", "params": {"question": "入职流程"}},
        "入职培训": {"action": "rag_query", "params": {"question": "入职培训"}},
        # 出差相关
        "出差": {"action": "rag_query", "params": {"question": "出差制度"}},
        # 福利相关
        "福利": {"action": "rag_query", "params": {"question": "福利政策"}},
        "五险一金": {"action": "rag_query", "params": {"question": "五险一金政策"}},
        # 办公用品
        "办公用品": {"action": "rag_query", "params": {"question": "办公用品申请"}},
    }

    # 个人偏好关键词 → memory_retrieval
    PREFERENCE_KEYWORDS = [
        "我喜欢",
        "我讨厌",
        "我爱",
        "我不喜欢",
        "我偏好",
        "我习惯",
    ]

    def match(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        匹配关键词规则，返回动作指令

        如果匹配到，返回 {"action": "xxx", "params": {...}, "reasoning": "xxx"}
        如果没有匹配，返回 None
        """
        # 1. 检查业务关键词（精确匹配）
        for keyword, action in self.KEYWORD_RULES.items():
            if keyword in user_input:
                logger.info(f"规则层匹配到关键词: {keyword} → {action}")
                return {
                    "action": action["action"],
                    "params": action["params"],
                    "reasoning": f"规则层识别到关键词 '{keyword}'，直接路由到 {action['action']}"
                }

        # 2. 检查个人偏好关键词
        for pref in self.PREFERENCE_KEYWORDS:
            if pref in user_input:
                logger.info(f"规则层匹配到偏好关键词: {pref} → memory_retrieval")
                return {
                    "action": "memory_retrieval",
                    "params": {"question": user_input},
                    "reasoning": f"规则层识别到用户偏好关键词 '{pref}'，路由到 memory_retrieval"
                }

        # 没有匹配到任何规则
        return None


# 全局实例
rule_layer = RuleLayer()