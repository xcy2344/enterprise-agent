from typing import Any, Dict, List, Optional

from app.tools.base_tool import BaseTool
from app.core.rag import RAGService


class RAGTool(BaseTool):
    """RAG 知识库查询工具"""

    def __init__(self):
        self._rag = RAGService()

    @property
    def name(self) -> str:
        return "rag_query"

    @property
    def description(self) -> str:
        return "查询企业内部知识库（包含公司政策、制度、流程、规定等信息）。当用户询问公司内部事务时使用此工具。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户的问题"
                }
            },
            "required": ["question"]
        }

    def execute(self, question: str, memory_context: Optional[List[Dict[str, Any]]] = None) -> dict:
        answer = self._rag.answer(question, memory_context)
        return {"success": True, "result": answer}
