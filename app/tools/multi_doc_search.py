from typing import Any, Dict

from app.core.vector_store import vector_store
from app.tools.base_tool import BaseTool
from app.utils.logger import logger


class MultiDocSearchTool(BaseTool):
    """
    跨多份文档检索工具

    在同一个向量库里按 source 分组返回相关段落，便于对比多份制度/政策/条款。
    """

    @property
    def name(self) -> str:
        return "multi_doc_search"

    @property
    def description(self) -> str:
        return "跨多份文档检索并对比相关内容。适用于需要对比多个制度、政策或合同条款的场景。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词或问题"},
                "top_k": {"type": "integer", "description": "检索条数，默认 5"}
            },
            "required": ["query"]
        }

    def execute(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """检索后按来源文档分组返回结果"""
        if not query:
            return {"success": False, "result": "缺少检索关键词 query"}

        try:
            top_k = int(top_k) if top_k else 5
        except (TypeError, ValueError):
            top_k = 5

        try:
            docs = vector_store.search(query, top_k=max(1, top_k))
        except Exception as e:
            logger.error(f"multi_doc_search 检索异常: {e}")
            return {"success": False, "result": f"检索失败: {e}"}

        if not docs:
            # 知识库非空却拿不到结果，说明是向量化/检索服务异常，而不是真的没有内容
            if vector_store.count() > 0:
                logger.error("multi_doc_search 检索服务异常：知识库非空但未返回任何结果")
                return {"success": False, "result": "检索服务暂时不可用，请稍后重试。"}
            return {"success": True, "result": "知识库为空，没有可检索的内容。"}

        # 按来源文档分组：{source: [doc, ...]}
        grouped: Dict[str, list] = {}
        for doc in docs:
            source = doc.get("source") or "未知来源"
            grouped.setdefault(source, []).append(doc)

        lines = [f"共命中 {len(docs)} 段内容，覆盖 {len(grouped)} 份文档："]
        for index, (source, items) in enumerate(grouped.items(), 1):
            lines.append(f"\n文档{index}（{source}）：")
            for item in items:
                lines.append(f"  - 相关度 {item.get('score', 0):.4f}：{item.get('text', '')}")

        logger.info(f"multi_doc_search 命中 {len(docs)} 段，覆盖 {len(grouped)} 份文档")
        return {"success": True, "result": "\n".join(lines)}
