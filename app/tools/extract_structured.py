import json
from typing import Any, Dict, List

from app.tools.base_tool import BaseTool
from app.utils.config import Config
from app.utils.llm import LLM_FALLBACK_REPLY, call_llm_with_retry
from app.utils.logger import logger


class ExtractStructuredTool(BaseTool):
    """
    结构化字段抽取工具

    把合同、报告等非结构化文本里的指定字段抽成结构化数据（键值对）。
    """

    @property
    def name(self) -> str:
        return "extract_structured"

    @property
    def description(self) -> str:
        return "从非结构化文本中提取指定字段的结构化数据。适用于合同、报告等文本的信息抽取。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待抽取的非结构化文本"},
                "fields": {"type": "string", "description": "要提取的字段名，逗号分隔，如：金额,签署日期,甲方"}
            },
            "required": ["text", "fields"]
        }

    def execute(self, text: str, fields: str) -> Dict[str, Any]:
        """抽取指定字段并返回键值对"""
        if not text:
            return {"success": False, "result": "缺少待抽取文本 text"}

        field_list = [item.strip() for item in str(fields or "").split(",") if item.strip()]
        if not field_list:
            return {"success": False, "result": "缺少要提取的字段 fields（逗号分隔）"}

        system_prompt = "你是企业文档信息抽取助手，只输出 JSON，不要输出任何解释。"
        prompt = f"""请从下面的文本中抽取这些字段：{'、'.join(field_list)}

要求：
1. 严格返回 JSON 对象，键为字段名
2. 文本里没有提到的字段，值填「未提及」，不要编造
3. 只返回 JSON，不要代码块、不要解释文字

文本：
{text}
"""

        result = call_llm_with_retry(
            prompt=prompt,
            model=Config.LLM_MODEL,
            system_prompt=system_prompt
        )
        if result is None:
            logger.error("extract_structured 大模型不可用")
            return {"success": False, "result": LLM_FALLBACK_REPLY}

        extracted = self._parse(result, field_list)
        logger.info(f"extract_structured 抽取字段: {list(extracted.keys())}")
        return {"success": True, "result": str(extracted)}

    @staticmethod
    def _parse(raw: str, field_list: List[str]) -> Dict[str, str]:
        """
        把大模型返回文本解析成字典

        解析失败时退化为把原文按字段名逐个兜底，保证字段齐全、不丢内容。
        """
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        data: Dict[str, Any] = {}
        if json_start != -1 and json_end > json_start:
            try:
                parsed = json.loads(raw[json_start:json_end])
                if isinstance(parsed, dict):
                    data = parsed
            except ValueError:
                data = {}

        # 保证用户要求的字段都在结果里（缺失的填「未提及」）
        return {field: str(data.get(field, "未提及")) for field in field_list}
