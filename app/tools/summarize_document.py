from typing import Any, Dict, List

from app.core.vector_store import vector_store
from app.tools.base_tool import BaseTool
from app.utils.config import Config
from app.utils.llm import LLM_FALLBACK_REPLY, call_llm_with_retry
from app.utils.logger import logger


class SummarizeDocumentTool(BaseTool):
    """
    文档摘要工具

    从向量库元数据里取出该文档的全部段落拼成全文，再交给大模型生成摘要。
    """

    @property
    def name(self) -> str:
        return "summarize_document"

    @property
    def description(self) -> str:
        return "对指定企业文档生成摘要，提取关键条款。适用于快速了解长文档要点。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "doc_name": {"type": "string", "description": "文档名（对应知识条目里的 source，如 policies_0、finance.md）"},
                "max_length": {"type": "integer", "description": "摘要最大字数，默认 200"}
            },
            "required": ["doc_name"]
        }

    def execute(self, doc_name: str, max_length: int = 200) -> Dict[str, Any]:
        """读取文档全文并生成摘要"""
        if not doc_name:
            return {"success": False, "result": "缺少文档名 doc_name"}

        try:
            max_length = int(max_length) if max_length else 200
        except (TypeError, ValueError):
            max_length = 200

        chunks = self._collect_chunks(doc_name)
        if not chunks:
            available = sorted({item.get("source", "") for item in vector_store.metadata})
            logger.warning(f"summarize_document 未找到文档: {doc_name}")
            return {
                "success": False,
                "result": f"未找到文档「{doc_name}」。当前知识库中的文档有：{'、'.join(available)}"
            }

        full_text = "\n".join(chunks)
        logger.info(f"summarize_document 文档 {doc_name} 共 {len(chunks)} 段，{len(full_text)} 字")

        system_prompt = "你是企业内部文档助理，擅长提炼制度、政策、合同类文档的要点。"
        prompt = f"""请对下面这份企业文档生成摘要，要求：
1. 不超过 {max_length} 字
2. 保留关键条款、数字、时间、审批流程等要点
3. 直接输出摘要正文，不要写「本文档介绍了」这类空话

文档（{doc_name}）内容：
{full_text}
"""

        summary = call_llm_with_retry(
            prompt=prompt,
            model=Config.LLM_MODEL,
            system_prompt=system_prompt
        )
        if summary is None:
            logger.error(f"summarize_document 生成摘要失败: {doc_name}")
            return {"success": False, "result": LLM_FALLBACK_REPLY}

        return {"success": True, "result": summary}

    @staticmethod
    def _collect_chunks(doc_name: str) -> List[str]:
        """
        取出指定文档的全部段落

        先按 source 精确匹配，再退化为包含匹配（例如用 "policies" 匹配到 policies.txt_0）。
        """
        metadata = vector_store.metadata or []
        exact = [item for item in metadata if item.get("source") == doc_name]
        if exact:
            return [item.get("text", "") for item in exact]

        lowered = doc_name.lower()
        fuzzy = [
            item for item in metadata
            if lowered in str(item.get("source", "")).lower()
        ]
        return [item.get("text", "") for item in fuzzy]
