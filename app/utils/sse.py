"""
SSE（Server-Sent Events）流式输出工具

事件格式：
    data: {"content": "文本增量"}

结束标记：
    data: [DONE]
"""

import json
from typing import Iterable, Iterator

from app.utils.llm import LLM_FALLBACK_REPLY
from app.utils.logger import logger

# StreamingResponse 的媒体类型
SSE_MEDIA_TYPE = "text/event-stream"

# 关闭缓存/缓冲，保证边生成边下发（含 Nginx 反代场景）
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# 流结束标记
SSE_DONE_EVENT = "data: [DONE]\n\n"


def sse_event(content: str) -> str:
    """
    把一段回答文本封装成 SSE 事件

    内容用 JSON 承载，避免换行等字符破坏 SSE 协议
    """
    return f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"


def sse_stream(chunks: Iterable[str]) -> Iterator[str]:
    """
    把文本增量迭代器包装成 SSE 事件流，结束时发送 [DONE]

    生成过程中出现未捕获异常时补发降级话术，保证客户端能拿到收尾信息
    """
    try:
        for chunk in chunks:
            if chunk:
                yield sse_event(chunk)
    except Exception as e:
        logger.error(f"流式输出异常: {e}")
        yield sse_event(LLM_FALLBACK_REPLY)
    yield SSE_DONE_EVENT
