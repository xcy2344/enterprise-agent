from typing import Any, Dict, List

from app.utils.config import Config
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger


# 所有子任务都失败时的友好提示
ALL_SUBTASKS_FAILED_REPLY = "抱歉，这个问题需要分几步处理，但执行过程中没能拿到有效结果，建议换一种问法或稍后重试。"


class Aggregator:
    """
    结果汇总器：把多个子任务的执行结果融合成一个完整回答

    强调「融会贯通」而不是逐条罗列，避免回答像流水账。
    """

    def __init__(self):
        self.model = Config.LLM_MODEL

    def aggregate(self, user_input: str, subtask_results: List[Dict[str, Any]]) -> str:
        """
        汇总子任务结果，生成最终回答

        参数：
            user_input: 用户原始问题
            subtask_results: [{"step": 1, "action": "...", "reason": "...", "success": True, "result": "..."}]

        返回：
            汇总后的回答文本；全部子任务失败时返回友好提示，不会抛异常
        """
        if not subtask_results:
            logger.warning("没有子任务结果可汇总")
            return ALL_SUBTASKS_FAILED_REPLY

        succeeded = [item for item in subtask_results if item.get("success") and item.get("result")]
        if not succeeded:
            logger.error(f"全部子任务执行失败: {subtask_results}")
            return ALL_SUBTASKS_FAILED_REPLY

        # 把子任务结果整理成给大模型看的材料（失败的子任务也标注出来，避免模型臆测）
        digest_lines = []
        for item in subtask_results:
            status = "成功" if item.get("success") else "失败"
            content = item.get("result") or "无结果"
            digest_lines.append(
                f"子任务 {item.get('step')}（{item.get('action')}，{status}）：{content}"
            )
        digest = "\n".join(digest_lines)

        system_prompt = """你是企业内部知识助手，需要把多个子任务的执行结果汇总成一段完整、自然的回答。
要求：
1. 综合所有子任务的结果，融会贯通地组织语言，不要说「第一个子任务」「第二个子任务」这类话
2. 只依据子任务结果汇总，不得引入子任务未提及的任何信息，不要用通用知识或常识去补充解释
3. 如果某个子任务的结论是「资料中未提及」或「没有查到」，最终回答中也要如实说明，不要替它补一个看起来合理的答案
4. 某个子任务失败时不要臆测它的内容，可以说明这部分暂时没有查到
5. 回答直接面向用户的原始问题，条理清晰、简明扼要，不要复述任务拆解过程"""

        prompt = f"""用户的原始问题：
{user_input}

各子任务的执行结果：
{digest}

请针对原始问题给出汇总回答。"""

        answer = call_llm_with_retry(
            prompt=prompt,
            model=self.model,
            system_prompt=system_prompt
        )

        # 大模型不可用：退化成把各子任务结果直接拼给用户，保证仍有可用输出
        if answer is None:
            logger.error("汇总大模型不可用，退化为直接拼接子任务结果")
            fallback = "\n".join(
                f"- {item.get('result')}" for item in succeeded
            )
            return f"（汇总服务暂不可用，以下是各部分结果）\n{fallback}"

        logger.info(f"子任务汇总完成，回答长度: {len(answer)} 字符")
        return answer
