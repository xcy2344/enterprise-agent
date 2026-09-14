"""
智核 · 企业知识 MCP 服务器

把企业知识能力（知识库问答、跨文档检索、文档摘要、结构化抽取、长期记忆）以
MCP（Model Context Protocol）工具的形式标准化暴露，供 Claude Desktop、Cursor 等
支持 MCP 的客户端直接调用。

两种运行方式：
1. 由 FastAPI 挂载（HTTP/SSE）：app/main.py 里 app.mount("/mcp", build_mcp_asgi_app())
   客户端连接地址为 http://localhost:8000/mcp/sse
2. 独立以 stdio 方式运行：python -m app.mcp_server（本地客户端可直接拉起进程）
"""

import functools
import inspect
import json
import logging
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from starlette.responses import Response

from app.core.memory import Memory
from app.core.rag import rag_service
from app.tools import get_tool
from app.utils.config import Config
from app.utils.logger import logger


# ===== MCP 调用日志：单独写入 logs/mcp_YYYYMMDD.log =====
def _build_mcp_logger() -> logging.Logger:
    """创建 MCP 专用日志器（与业务日志分开，便于排查外部调用）"""
    mcp_logger = logging.getLogger("enterprise_kb_mcp")
    mcp_logger.setLevel(logging.INFO)
    if mcp_logger.handlers:
        return mcp_logger

    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler(
        f"logs/mcp_{datetime.now().strftime('%Y%m%d')}.log",
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - MCP - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    mcp_logger.addHandler(handler)
    return mcp_logger


_mcp_logger = _build_mcp_logger()


def log_mcp_call(func):
    """
    MCP 工具调用日志装饰器

    调用前记录工具名与参数，调用后记录耗时与返回长度，异常时记录错误。
    显式保留原函数签名与注解，保证 FastMCP 生成的工具入参 schema 正确。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            params = json.dumps(kwargs, ensure_ascii=False, default=str)
        except Exception:
            params = str(kwargs)
        _mcp_logger.info(f"调用工具 {func.__name__} | 参数={params}")

        try:
            result = func(*args, **kwargs)
        except Exception as e:
            cost = (time.time() - start) * 1000
            _mcp_logger.error(f"工具 {func.__name__} 失败 | 耗时 {cost:.1f}ms | 错误: {e}")
            raise

        cost = (time.time() - start) * 1000
        _mcp_logger.info(
            f"工具 {func.__name__} 成功 | 耗时 {cost:.1f}ms | 返回 {len(str(result))} 字符"
        )
        return result

    wrapper.__signature__ = inspect.signature(func)
    wrapper.__annotations__ = getattr(func, "__annotations__", {})
    return wrapper


mcp = FastMCP("智核")


@mcp.tool()
@log_mcp_call
def rag_query(question: str) -> str:
    """查询企业内部知识库，回答公司政策、制度、流程等问题"""
    return rag_service.answer(question)


@mcp.tool()
@log_mcp_call
def multi_doc_search(query: str, top_k: int = 5) -> str:
    """跨多份文档检索并对比相关内容。适用于需要对比多个制度、政策或合同条款的场景。"""
    return str(get_tool("multi_doc_search").execute(query=query, top_k=top_k).get("result", ""))


@mcp.tool()
@log_mcp_call
def summarize_document(doc_name: str, max_length: int = 200) -> str:
    """对指定企业文档生成摘要，提取关键条款。适用于快速了解长文档要点。"""
    return str(get_tool("summarize_document").execute(doc_name=doc_name, max_length=max_length).get("result", ""))


@mcp.tool()
@log_mcp_call
def extract_structured(text: str, fields: str) -> str:
    """从非结构化文本中提取指定字段的结构化数据。适用于合同、报告等文本的信息抽取。"""
    return str(get_tool("extract_structured").execute(text=text, fields=fields).get("result", ""))


@mcp.tool()
@log_mcp_call
def memory_retrieval(user_id: str, type: str = "preference") -> str:
    """从用户长期记忆中检索信息。type 可选 'preference'（偏好）或 'history'（历史查询）"""
    memory = Memory(user_id)
    if type == "history":
        return str(memory.get_user_profile().get("history_queries", []))
    return str(memory.get_user_profile().get("preferences", {}))


# ===== 端点信息与鉴权 =====

def _relative_path(scope: Dict[str, Any]) -> str:
    """取挂载点内部的相对路径（挂载在 /mcp 时，根路径会表现为 "" 或 "/"）"""
    path = scope.get("path", "") or ""
    root = scope.get("root_path", "") or ""
    if root and path.startswith(root):
        path = path[len(root):]
    return path or "/"


def _authorized(scope: Dict[str, Any], token: str) -> bool:
    """校验 Authorization: Bearer <token>"""
    expected = f"Bearer {token}"
    for key, value in scope.get("headers") or []:
        if key == b"authorization":
            provided = value.decode("latin-1")
            return secrets.compare_digest(provided, expected)
    return False


def _info_payload() -> Dict[str, Any]:
    """GET /mcp 返回的服务信息，方便快速确认端点可达与鉴权状态"""
    return {
        "server": "智核 · 企业知识 MCP 中枢",
        "transport": "sse",
        "sse_endpoint": "/mcp/sse",
        "messages_endpoint": "/mcp/messages/",
        "auth": "已启用（Authorization: Bearer <MCP_AUTH_TOKEN>）" if Config.MCP_AUTH_TOKEN else "未启用（本地开发模式）",
        "tools": [tool.name for tool in getattr(mcp, "_tool_manager")._tools.values()] if hasattr(mcp, "_tool_manager") else [],
    }


def build_mcp_asgi_app():
    """
    构造带鉴权的 MCP ASGI 应用，供 FastAPI 挂载

    - GET /mcp          返回服务信息
    - GET /mcp/sse      SSE 通道（客户端从这里建立连接）
    - POST /mcp/messages/  客户端消息回传
    - 配置了 MCP_AUTH_TOKEN 时，除信息页外都要求 Bearer Token
    """
    inner = mcp.sse_app()

    async def app(scope, receive, send):
        if scope.get("type") != "http":
            await inner(scope, receive, send)
            return

        if _relative_path(scope) == "/":
            body = json.dumps(_info_payload(), ensure_ascii=False).encode("utf-8")
            await Response(body, media_type="application/json")(scope, receive, send)
            return

        token = Config.MCP_AUTH_TOKEN
        if token and not _authorized(scope, token):
            logger.warning(f"MCP 鉴权失败，路径: {_relative_path(scope)}")
            body = json.dumps(
                {"error": "unauthorized", "message": "缺少或错误的 MCP Bearer Token"},
                ensure_ascii=False
            ).encode("utf-8")
            await Response(body, status_code=401, media_type="application/json")(scope, receive, send)
            return

        await inner(scope, receive, send)

    return app


if __name__ == "__main__":
    # 以 stdio 方式独立运行（Claude Desktop / Cursor 本地进程模式）
    logger.info("以 stdio 模式启动 MCP 服务器")
    mcp.run()
