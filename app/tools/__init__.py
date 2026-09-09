from app.tools.base_tool import BaseTool
from app.tools.rag_tool import RAGTool
from app.tools.calculator import CalculatorTool
from app.tools.http_request import HttpRequestTool

TOOLS = {
    RAGTool().name: RAGTool(),
    CalculatorTool().name: CalculatorTool(),
    HttpRequestTool().name: HttpRequestTool(),
}


def get_tool(name: str) -> BaseTool:
    return TOOLS.get(name)


def list_tools() -> list:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in TOOLS.values()
    ]