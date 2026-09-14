import json
from typing import Any, Dict, List, Optional

from app.tools import list_tools
from app.utils.config import Config
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger


# 多诉求特征词：用户问题里出现任意一个，就认为可能需要拆解成多个子任务
MULTI_INTENT_KEYWORDS = ["对比", "然后", "分别", "以及"]


# 工具的完整签名说明（P1 / P3）：拆解时把签名明确写进提示词，
# 避免大模型把中文句子传给 calculator、或给 summarize_document 传错参数。
# 未收录的工具会退化成「名称 + 描述」，因此新增工具时可在此补充签名。
TOOL_SIGNATURES = {
    "rag_query": 'rag_query(question: str)：查询企业知识库，question 是自然语言问题',
    "calculator": 'calculator(expression: str)：只接受纯数学表达式，如 "128*7"、"5+3"；'
                  '只能包含数字和运算符 + - * / ( ) . 与空格，绝对不能包含中文',
    "summarize_document": 'summarize_document(doc_name: str)：需要文档名（知识库里条目的 source），不是文本内容',
    "multi_doc_search": 'multi_doc_search(query: str, top_k: int = 5)：跨多份文档检索，query 是检索关键词',
    "extract_structured": 'extract_structured(text: str, fields: str)：text 是要抽取的原文，fields 是逗号分隔的字段名',
    "http_request": 'http_request(url: str, method: str = "GET")：发起 HTTP 请求',
}


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
            [f"- {self._tool_signature(t)}" for t in list_tools()]
        )

        prompt = f"""你是一个任务分解器。请把用户的问题拆解成按顺序执行的子任务。

可用工具（括号里是参数签名，请严格按签名传参）：
{tools_desc}

拆解要求：
1. 子任务数量优先控制在 2~3 个；只有确实需要更多步骤时才增加，最多不超过 {self.max_subtasks} 个
2. 先数清楚用户有几个不同的意图，每个不同意图对应一个子任务
   （例如「对比年假和调休的区别」是意图一，「休5天需要提前几天申请」是意图二，应拆成 2 个子任务）
3. 只有当两个诉求本质上是同一件事、一次检索就能一起回答时，才合并成一个子任务；
   不要为了少几步就把所有诉求合并成一个子任务，也不要反复检索同一个问题
4. 每个子任务只做一件事，按执行先后顺序排列
5. action 必须从上面的工具名中选择，不要创造新工具名
6. params 必须严格符合工具签名：
   - rag_query 用 {{"question": "自然语言问题"}}
   - calculator 的 expression 只能是数字和运算符（+ - * / ( ) . 和空格），例如 "128*7"、"5+3"；
     expression 不能包含中文，也不能把自然语言句子写进 expression
   - summarize_document 需要 doc_name（文档名），不要传 content / text
7. 每个子任务的 params.question 必须自包含：保留原问题里的关键限定词，不要因为拆解而丢失上下文
   （例如要写成「休5天年假需要提前几天申请」，不能写成「休5天需要提前几天申请」——后者检索时会跑偏）
8. reason 用一句话说明为什么需要这一步
9. 如果问题本身很简单（只有一个意图），就只返回 1 个子任务

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

    @staticmethod
    def _tool_signature(tool: Dict[str, Any]) -> str:
        """
        生成工具的签名说明（P3）

        优先使用预置的完整签名（含参数类型与取值约束），未收录的工具退化为
        「名称: 描述」，保证新增工具时不会与工具注册表脱节。
        """
        name = tool.get("name", "")
        return TOOL_SIGNATURES.get(name) or f"{name}: {tool.get('description', '')}"

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
        seen_signatures = set()
        for index, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if not action:
                continue
            params = item.get("params") or {}
            # P1：action 与参数完全相同的子任务属于重复拆分，直接合并（大模型偶发同义重复）
            signature = (action, json.dumps(params, sort_keys=True, ensure_ascii=False))
            if signature in seen_signatures:
                logger.warning(f"子任务 {index}（action={action}）与前面的子任务重复，已合并跳过")
                continue
            seen_signatures.add(signature)
            subtasks.append({
                "step": item.get("step") or index,
                "action": action,
                "params": params,
                "reason": item.get("reason", ""),
            })
            if len(subtasks) >= self.max_subtasks:
                logger.warning(f"子任务数量超过上限 {self.max_subtasks}，已截断")
                break

        return subtasks or None
