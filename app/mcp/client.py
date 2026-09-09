from typing import Dict, Any, Optional
import requests
import json
from app.utils.logger import logger


class MCPClient:
    """
    MCP 协议客户端：统一协议连接外部系统

    模拟 Model Context Protocol 标准
    通过标准化的 JSON-RPC 格式与外部服务通信
    """

    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url
        self.session_id = None

    def connect(self, server_url: str) -> bool:
        """连接 MCP 服务器"""
        self.server_url = server_url
        logger.info(f"MCP 客户端连接到: {server_url}")
        return True

    def call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 MCP 协议调用外部工具

        协议格式:
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "tool_name",
                "arguments": {...}
            },
            "id": 1
        }
        """
        if not self.server_url:
            logger.warning("MCP 服务器未配置，使用模拟模式")

        # 构建 MCP 请求
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params
            },
            "id": 1
        }

        logger.info(f"MCP 调用: {tool_name}, params={params}")

        try:
            if self.server_url:
                response = requests.post(
                    self.server_url,
                    json=request,
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    return {"success": True, "result": result.get("result", {})}
                else:
                    return {"success": False, "error": f"HTTP {response.status_code}"}
            else:
                # 模拟模式：根据工具名返回模拟数据
                return self._mock_call(tool_name, params)
        except Exception as e:
            logger.error(f"MCP 调用失败: {e}")
            return {"success": False, "error": str(e)}

    def _mock_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """模拟 MCP 调用（用于测试）"""
        if tool_name == "get_weather":
            city = params.get("city", "深圳")
            return {
                "success": True,
                "result": {
                    "city": city,
                    "weather": "晴天",
                    "temperature": "25°C",
                    "humidity": "65%"
                }
            }
        elif tool_name == "get_time":
            from datetime import datetime
            return {
                "success": True,
                "result": {
                    "time": datetime.now().isoformat()
                }
            }
        else:
            return {
                "success": False,
                "error": f"未知工具: {tool_name}"
            }


# 全局 MCP 客户端
mcp_client = MCPClient()