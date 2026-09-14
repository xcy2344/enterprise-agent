from app.tools.base_tool import BaseTool
from app.tools.rag_tool import RAGTool
from app.tools.calculator import CalculatorTool
from app.tools.http_request import HttpRequestTool
from app.tools.multi_doc_search import MultiDocSearchTool
from app.tools.summarize_document import SummarizeDocumentTool
from app.tools.extract_structured import ExtractStructuredTool

TOOLS = {
    RAGTool().name: RAGTool(),
    CalculatorTool().name: CalculatorTool(),
    HttpRequestTool().name: HttpRequestTool(),
    MultiDocSearchTool().name: MultiDocSearchTool(),
    SummarizeDocumentTool().name: SummarizeDocumentTool(),
    ExtractStructuredTool().name: ExtractStructuredTool(),
}


def get_tool(name: str) -> BaseTool:
    return TOOLS.get(name)


def list_tools() -> list:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in TOOLS.values()
    ]