import time
from typing import Iterator, List, Optional

import dashscope
from dashscope import Generation

from app.utils.config import Config
from app.utils.logger import logger


# 大模型彻底不可用（所有重试均失败）时的降级回复
LLM_FALLBACK_REPLY = "当前服务繁忙，请稍后重试。"


def _build_messages(
    prompt: str,
    system_prompt: str = None,
    history: List[dict] = None
) -> List[dict]:
    """
    构造 messages 参数（system 提示词、对话历史均可选）

    参数：
        prompt: 本轮用户提示词
        system_prompt: 系统提示词，可选
        history: 对话历史（如 ShortTermMemory.history），可选

    说明：
        记忆中的 role="system" 条目（历史对话摘要）会与 system_prompt 合并成开头的系统消息，
        user/assistant 条目按原顺序保留，避免只支持 user/assistant 时把摘要丢掉。
        若历史里最后一条 user 消息与本次 prompt 内容相同（调用方先写入记忆再取上下文），
        则跳过它，避免把当前问题重复传给模型。
    """
    system_parts: List[str] = []
    if system_prompt:
        system_parts.append(system_prompt)

    messages: List[dict] = []
    for message in history or []:
        role = message.get("role")
        content = message.get("content")
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == prompt:
        messages.pop()

    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})

    messages.append({"role": "user", "content": prompt})
    return messages


def call_llm_with_retry(
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    history: List[dict] = None
) -> Optional[str]:
    """
    调用大模型生成回答，失败时按指数退避重试

    参数：
        prompt: 用户提示词
        model: 模型名称，默认取 Config.LLM_MODEL
        system_prompt: 系统提示词，可选
        history: 对话历史（含 role="system" 的历史摘要），可选

    返回：
        模型返回的文本；重试 MAX_RETRIES 次后仍失败则返回 None
     """
    model = model or Config.LLM_MODEL
    dashscope.api_key = Config.DASHSCOPE_API_KEY

    messages = _build_messages(prompt, system_prompt, history)

    total_attempts = Config.MAX_RETRIES + 1

    for attempt in range(total_attempts):
        try:
            response = Generation.call(
                model=model,
                messages=messages,
                result_format="message"
            )

            # 超时、限流、鉴权失败等 API 错误：SDK 不抛异常，而是返回非 200 状态码
            status_code = getattr(response, "status_code", None)
            if status_code != 200:
                raise RuntimeError(
                    f"API 返回异常状态码 {status_code}: {getattr(response, 'message', '')}"
                )

            content = response.output.choices[0].message.content
            if not content:
                raise ValueError("大模型返回内容为空")

            if attempt > 0:
                logger.info(f"大模型重试成功（第 {attempt + 1} 次尝试）")
            return content

        except Exception as e:
            if attempt + 1 < total_attempts:
                delay = Config.RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    f"大模型调用失败（第 {attempt + 1}/{total_attempts} 次）: {e}，{delay} 秒后重试"
                )
                time.sleep(delay)
            else:
                logger.error(f"大模型调用失败，已重试 {Config.MAX_RETRIES} 次: {e}")

    return None


def call_llm_stream(
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    history: List[dict] = None
) -> Iterator[str]:
    """
    流式调用大模型，逐块 yield 文本增量

    参数与 call_llm_with_retry 相同。

    返回：
        文本增量的生成器；在尚未产出任何内容前失败会按指数退避重试，
        重试耗尽则结束迭代（不抛异常），由上层决定是否兜底。

    注意：
        一旦已经开始产出内容，中途失败不再重试（否则会重复输出），而是抛出异常，
        由上层（API 层）补发兜底提示，避免客户端拿到被默默截断的回答。
    """
    model = model or Config.LLM_MODEL
    dashscope.api_key = Config.DASHSCOPE_API_KEY

    messages = _build_messages(prompt, system_prompt, history)
    total_attempts = Config.MAX_RETRIES + 1

    for attempt in range(total_attempts):
        produced = False
        try:
            responses = Generation.call(
                model=model,
                messages=messages,
                result_format="message",
                stream=True,
                incremental_output=True
            )

            for response in responses:
                # 超时、限流、鉴权失败等 API 错误：SDK 不抛异常，而是返回非 200 状态码
                status_code = getattr(response, "status_code", None)
                if status_code != 200:
                    raise RuntimeError(
                        f"API 返回异常状态码 {status_code}: {getattr(response, 'message', '')}"
                    )

                content = response.output.choices[0].message.content
                if content:
                    produced = True
                    yield content

            if produced:
                return
            raise ValueError("大模型流式返回为空")

        except Exception as e:
            if produced:
                logger.error(f"流式输出中断（已输出部分内容，不再重试）: {e}")
                raise
            if attempt + 1 < total_attempts:
                delay = Config.RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    f"流式调用失败（第 {attempt + 1}/{total_attempts} 次）: {e}，{delay} 秒后重试"
                )
                time.sleep(delay)
            else:
                logger.error(f"流式调用失败，已重试 {Config.MAX_RETRIES} 次: {e}")
