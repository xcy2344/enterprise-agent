import json
from typing import Any, Dict, List, Optional

from app.tools import list_tools
from app.utils.config import Config
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger


# 多诉求特征词：用户问题里出现任意一个，就认为可能需要拆解成多个子任务
MULTI_INTENT_KEYWORDS = ["对比", "然后", "分别", "以及"]


class TaskDecomposer:
    """
    任务分解器：把包含多个诉求的复杂问题拆成可顺序执行的子任务

    只负责拆解，不负责执行；执行由 Executor 完成，最后交给 Aggregator 汇总。
    """

    def __init__(self):
        self.model = Config.LLM_MODEL
        self.max_subtasks = Config.MAX_SUBTASKS

    @staticmethod
    def needs_decomposition(user_input: str) -> bool:
        """
        判断是否需要走任务分解

        纯关键词规则判断，不消耗 Token；开关由 Config.ENABLE_TASK_DECOMPOSITION 控制。
        """
        if not Config.ENABLE_TASK_DECOMPOSITION or not user_input:
            return False
        return any(keyword in user_input for keyword in MULTI_INTENT_KEYWORDS)

    def decompose(
        self,
        user_input: str,
        memory_context: List[Dict] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        把用户问题拆解为子任务列表

        返回格式：
            [{"step": 1, "action": "工具名", "params": {...}, "reason": "为什么"}]

        说明：
            只有一个子任务时同样返回长度为 1 的列表；
            大模型不可用或解析失败时返回 None，由上层回退到单步规划。
        """
        tools_desc = "\n".join(
            [f"- {t['name']}: {t['description']}" for t in list_tools()]
        )

        prompt = f"""你是一个任务分解器。请把用户的问题拆解成按顺序执行的子任务。

可用工具：
{tools_desc}

拆解要求：
1. 每个子任务只做一件事，按执行先后顺序排列
2. action 必须从上面的工具名中选择，不要创造新工具名
3. params 是该工具的入参，例如 rag_query 用 {{"question": "..."}}，calculator 用 {{"expression": "..."}}
4. reason 用一句话说明为什么需要这一步
5. 最多拆成 {self.max_subtasks} 个子任务；如果问题本身很简单，就只返回 1 个子任务

用户问题：{user_input}

只返回 JSON 数组，不要任何解释文字，格式：
[
    {{"step": 1, "action": "rag_query", "params": {{"question": "..."}}, "reason": "..."}}
]
"""

        # 大模型调用（内部含重试与指数退避）
        result = call_llm_with_retry(prompt=prompt, model=self.model)
        if result is None:
            logger.error("任务分解失败：大模型不可用，回退到单步规划")
            return None

        logger.info(f"任务分解原始返回: {result}")
        subtasks = self._parse(result)
        if not subtasks:
            logger.warning("任务分解失败：大模型返回无法解析为子任务列表")
            return None

        logger.info(f"任务分解完成，共 {len(subtasks)} 个子任务")
        return subtasks

    def _parse(self, raw: str) -> Optional[List[Dict[str, Any]]]:
        """
        从大模型返回文本中解析子任务列表

        兼容模型在 JSON 前后加解释文字、用代码块包裹等情况；解析失败返回 None。
        """
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start == -1 or json_end <= json_start:
            return None

        try:
            data = json.loads(raw[json_start:json_end])
        except ValueError as e:
            logger.warning(f"子任务列表 JSON 解析失败: {e}")
            return None

        if not isinstance(data, list):
            return None

        subtasks: List[Dict[str, Any]] = []
        for index, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if not action:
                continue
            subtasks.append({
                "step": item.get("step") or index,
                "action": action,
                "params": item.get("params") or {},
                "reason": item.get("reason", ""),
            })
            if len(subtasks) >= self.max_subtasks:
                logger.warning(f"子任务数量超过上限 {self.max_subtasks}，已截断")
                break

        return subtasks or None
