import dashscope
from dashscope import Generation
from app.core.vector_store import vector_store
from app.utils.config import Config
from app.utils.logger import logger


class RAGService:
    """
    业务层：RAG 问答服务
    流程：用户提问 → 检索知识库 → 构建 Prompt → 调用大模型 → 返回答案
    """

    def __init__(self):
        self.vector_store = vector_store
        self.model = Config.LLM_MODEL
        self.top_k = Config.TOP_K

        # 设置 API Key
        dashscope.api_key = Config.DASHSCOPE_API_KEY

    def answer(self, question: str) -> str:
        """
        处理用户问题，返回 AI 回答
        """
        logger.info(f"收到用户问题: {question}")

        # 步骤1：检索知识库
        docs = self.vector_store.search(question, top_k=self.top_k)

        # 如果没找到任何资料
        if not docs:
            logger.warning(f"未找到相关知识，问题: {question}")
            return "抱歉，当前知识库中没有找到与您问题相关的内容。"

        # 步骤2：构建 Prompt
        context = "\n".join([doc["text"] for doc in docs])

        system_prompt = """你是一个企业智能客服助手。

【重要原则】
1. 先判断【参考资料】是否与【用户问题】相关
2. 如果参考资料完全不相关，直接说"未找到与您问题直接相关的内容"
3. 如果参考资料中有多条内容，优先选择与问题关键词最直接相关的那一条回答
4. 回答时标注你引用了哪份资料（如"根据加班政策..."）
5. 只根据【参考资料】回答问题，不要编造知识

【回答格式】
如果找到了相关内容：
"根据【资料来源】，[具体回答内容]。"

如果未找到相关内容：
"未找到与您问题直接相关的内容，建议您提供更多关键词或咨询相关部门。"
"""

        user_prompt = f"""
【参考资料】
{context}

【用户问题】
{question}

请根据参考资料回答用户的问题。"""

        # 步骤3：调用大模型生成回答
        try:
            response = Generation.call(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                result_format="message"
            )

            answer = response.output.choices[0].message.content
            logger.info(f"生成回答成功，长度: {len(answer)} 字符")
            return answer

        except Exception as e:
            logger.error(f"大模型调用失败: {e}")
            return "抱歉，系统出现错误，请稍后重试。"


# 创建全局实例
rag_service = RAGService()