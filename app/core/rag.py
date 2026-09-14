from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.vector_store import vector_store
from app.utils.config import Config
from app.utils.llm import LLM_FALLBACK_REPLY, call_llm_stream, call_llm_with_retry
from app.utils.logger import logger


# 检索结果与问题相关性不足时的兜底回复（不调用大模型，避免编造答案）
NO_RELEVANT_CONTENT_REPLY = "未找到与您问题直接相关的内容，建议您换一种问法或咨询相关部门。"

# 知识库为空时的兜底回复
EMPTY_KNOWLEDGE_REPLY = "抱歉，当前知识库中没有找到与您问题相关的内容。"


class RAGService:
    """
    业务层：RAG 问答服务
    流程：用户提问 → 检索知识库 → 检索质量评估 → 构建 Prompt → 调用大模型 → 返回答案
    提供 answer（一次性返回完整回答）和 answer_stream（流式逐块返回）两种输出方式
    """

    def __init__(self):
        self.vector_store = vector_store
        self.model = Config.LLM_MODEL
        self.top_k = Config.TOP_K
        self.score_threshold = Config.RAG_SCORE_THRESHOLD

    def answer(self, question: str, memory_context: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        处理用户问题，返回完整 AI 回答（非流式）

        参数：
            question: 用户问题
            memory_context: 对话历史（含 role="system" 的历史摘要），可选。
                            传入后作为多轮上下文一起发给大模型，
                            便于回答“我前面提到过什么”这类追问。
        """
        logger.info(f"收到用户问题: {question}")

        # 步骤1、2：检索知识库 + 检索质量评估（命中兜底时直接返回，不调用大模型）
        docs, reply = self._retrieve_relevant(question)
        if reply is not None:
            return reply

        # 步骤3：构建 Prompt
        system_prompt, user_prompt = self._build_prompts(question, docs, memory_context)

        # 步骤4：调用大模型生成回答（内部含重试与指数退避）
        answer = call_llm_with_retry(
            prompt=user_prompt,
            model=self.model,
            system_prompt=system_prompt,
            history=self._history_for_llm(memory_context)
        )

        # 重试后仍失败：降级回复，不让接口报错
        if answer is None:
            logger.error(f"大模型不可用，返回降级回复，问题: {question}")
            return LLM_FALLBACK_REPLY

        logger.info(f"生成回答成功，长度: {len(answer)} 字符")
        return answer

    def answer_stream(self, question: str, memory_context: Optional[List[Dict[str, Any]]] = None) -> Iterator[str]:
        """
        处理用户问题，流式返回 AI 回答

        流程与 answer 一致（检索 → 检索质量评估 → 构建 Prompt），
        区别是最后用流式接口逐块 yield 文本增量；
        兜底/降级场景一次性 yield 完整话术。

        参数：
            question: 用户问题
            memory_context: 对话历史（含 role="system" 的历史摘要），可选
        """
        logger.info(f"收到用户问题（流式）: {question}")

        # 步骤1、2：检索知识库 + 检索质量评估（命中兜底时直接 yield 话术，不调用大模型）
        docs, reply = self._retrieve_relevant(question)
        if reply is not None:
            yield reply
            return

        # 步骤3：构建 Prompt
        system_prompt, user_prompt = self._build_prompts(question, docs, memory_context)

        # 步骤4：流式调用大模型，逐块产出文本增量
        produced = False
        for chunk in call_llm_stream(
            prompt=user_prompt,
            model=self.model,
            system_prompt=system_prompt,
            history=self._history_for_llm(memory_context)
        ):
            produced = True
            yield chunk

        # 重试后仍无任何内容产出：降级回复，避免客户端拿到空回答
        if not produced:
            logger.error(f"大模型不可用，返回降级回复，问题: {question}")
            yield LLM_FALLBACK_REPLY

    def _retrieve_relevant(
        self,
        question: str
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        检索知识库并做检索质量评估

        返回 (docs, reply)：
        - 检索结果可用：(docs, None)
        - 需要直接兜底：(None, 兜底话术)，此时不应调用大模型
        """
        # 步骤1：检索知识库
        docs = self.vector_store.search(question, top_k=self.top_k)

        # 如果没找到任何资料
        if not docs:
            # 知识库里有数据却检索不到任何结果，说明 Embedding/检索服务异常，而不是知识库本身为空
            if self.vector_store.count() > 0:
                logger.error(f"检索服务异常，知识库共 {self.vector_store.count()} 条却未返回结果，问题: {question}")
                return None, LLM_FALLBACK_REPLY
            logger.warning(f"知识库为空，未找到相关知识，问题: {question}")
            return None, EMPTY_KNOWLEDGE_REPLY

        # 步骤2：检索质量评估：最高相似度低于阈值说明问题超出知识库范围
        max_score = max(doc["score"] for doc in docs)
        if max_score < self.score_threshold:
            logger.warning(
                f"检索相关性不足，最高分 {max_score:.4f} < 阈值 {self.score_threshold}，"
                f"跳过调用大模型，问题: {question}"
            )
            return None, NO_RELEVANT_CONTENT_REPLY

        logger.info(f"检索相关性通过，最高分 {max_score:.4f} >= 阈值 {self.score_threshold}")
        return docs, None

    def _build_prompts(
        self,
        question: str,
        docs: List[Dict[str, Any]],
        memory_context: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[str, str]:
        """构建系统提示词和用户提示词"""
        context = "\n".join([doc["text"] for doc in docs])

        system_prompt = """你是一个企业智能客服助手。

【重要原则】
1. 先判断【参考资料】是否与【用户问题】相关
2. 如果参考资料完全不相关，直接说"未找到与您问题直接相关的内容"
3. 如果参考资料中有多条内容，优先选择与问题关键词最直接相关的那一条回答
4. 回答时标注你引用了哪份资料（如"根据加班政策..."）
5. 只根据【参考资料】回答问题，不要编造知识，也不要使用参考资料之外的通用知识、常识或自己的理解去补充解释（P4：这是幻觉的主要来源）
6. 参考资料里没有出现的概念，不要给出它的定义、解释或行业惯例；直接说明「资料中未提及 X」，不要用一个看起来合理的说法填上
7. 禁止用「通常是指」「一般来说」「通常认为」「顾名思义」这类句式给参考资料之外的概念下定义
   反例（绝对不要这样写）：「调休通常是指因加班而获得的休息时间」——参考资料里没有这句话，就不允许写出来
8. 判断标准：写下的每一句话，都要能在【参考资料】里找到出处；找不到就不写

【回答格式】
如果找到了相关内容：
"根据【资料来源】，[具体回答内容]。"

如果未找到相关内容：
"未找到与您问题直接相关的内容，建议您提供更多关键词或咨询相关部门。"
"""

        # 记忆中存在 role="system" 的历史摘要时，说明这是多轮对话，补充说明可以结合历史回答
        if self._has_history_summary(memory_context):
            system_prompt += """
【对话历史】
本次对话还附带了更早的历史记录（含历史摘要）。如果用户是在追问此前提到过的信息
（例如“我前面提到过什么”），可以结合对话历史回答；否则仍以【参考资料】为准。"""

        user_prompt = f"""
【参考资料】
{context}

【用户问题】
{question}

请根据参考资料回答用户的问题。"""

        return system_prompt, user_prompt

    @staticmethod
    def _has_history_summary(memory_context: Optional[List[Dict[str, Any]]]) -> bool:
        """判断对话历史中是否存在 role="system" 的历史摘要条目"""
        return any(
            message.get("role") == "system" and message.get("content")
            for message in (memory_context or [])
        )

    @classmethod
    def _history_for_llm(
        cls,
        memory_context: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        取出需要传给大模型的对话历史

        只有存在真正历史（历史摘要，或不止一条对话消息）时才返回记忆内容，
        否则返回 None，避免把当前问题当成历史重复传给大模型。
        """
        if not memory_context:
            return None

        conversation = [
            message for message in memory_context
            if message.get("role") != "system"
        ]
        if not cls._has_history_summary(memory_context) and len(conversation) <= 1:
            return None
        return memory_context


# 创建全局实例
rag_service = RAGService()
