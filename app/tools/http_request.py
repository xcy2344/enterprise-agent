import requests
from app.tools.base_tool import BaseTool
from app.utils.logger import logger


class HttpRequestTool(BaseTool):
    """HTTP 请求工具（模拟 MCP 能力）"""

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return "发送 HTTP 请求，获取外部 API 数据。当用户需要实时信息（如天气、新闻）或调用外部 API 时使用。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "API 地址"},
                "method": {"type": "string", "description": "请求方法: GET/POST", "default": "GET"}
            },
            "required": ["url"]
        }

    def execute(self, url: str, method: str = "GET") -> dict:
        try:
            if method.upper() == "GET":
                response = requests.get(url, timeout=5)
            else:
                response = requests.post(url, timeout=5)

            if response.status_code == 200:
                return {"success": True, "result": response.text[:500]}
            else:
                return {"success": False, "result": f"请求失败: 状态码 {response.status_code}"}
        except Exception as e:
            return {"success": False, "result": f"请求异常: {e}"}