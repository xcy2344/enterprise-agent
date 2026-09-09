from app.tools.base_tool import BaseTool


class CalculatorTool(BaseTool):
    """计算器工具"""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "执行数学计算。当用户需要计算、统计、求和、求平均值等数学运算时使用。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '2+3*4' 或 'sum(1,2,3,4)'"
                }
            },
            "required": ["expression"]
        }

    def execute(self, expression: str) -> dict:
        try:
            # 安全评估（仅允许数字和基本运算符）
            allowed_names = {"sum": sum, "min": min, "max": max, "abs": abs}
            # 使用 ast.literal_eval 更安全，但这里简化处理
            # 注意：实际生产环境需要更严格的安全检查
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return {"success": True, "result": f"计算结果: {expression} = {result}"}
        except Exception as e:
            return {"success": False, "result": f"计算失败: {e}"}