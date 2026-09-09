from typing import Dict, Any
from app.core.memory import Memory
from app.core.planner import Planner
from app.core.executor import Executor
from app.core.reflector import Reflector
from app.utils.logger import logger
from app.utils.observability import start_trace, get_current_trace, end_trace


class AgentLoop:
    """Agent 核心循环（含反思机制 + 可观测追踪）"""

    def __init__(self):
        self.planner = Planner()
        self.executor = Executor()
        self.reflector = Reflector()
        self.max_cycles = 3

    def run(self, user_input: str, user_id: str = "default_user") -> Dict[str, Any]:
        # 1. 启动追踪
        trace = start_trace(user_id, user_input)
        logger.info(f"Agent 开始处理: user_id={user_id}, input={user_input}")

        try:
            # 2. 加载记忆
            trace.step_start("memory_load")
            memory = Memory(user_id)
            memory.add_user_message(user_input)
            context = memory.get_context()
            user_profile = memory.get_user_profile()
            trace.step_end("memory_load", {"context_len": len(context), "profile": user_profile})

            # 3. Planner 决策
            trace.step_start("planner")
            plan = self.planner.plan(user_input, context, user_profile)
            logger.info(f"Planner 决策: {plan}")
            trace.step_end("planner", plan)

            # 4. Executor 执行
            trace.step_start("executor")
            result = self.executor.execute(plan, user_profile)
            logger.info(f"Executor 结果: {result}")
            trace.step_end("executor", result)

            # ===== 保存偏好 =====
            if result.get("need_save"):
                prefs = result.get("preferences", {})
                if prefs:
                    memory.update_preferences(prefs)
                    logger.info(f"已存储用户偏好: {prefs}")
                    # 更新结果中的回答
                    result["result"] = f"已记录您的偏好: {prefs}"

            # 5. 存储当前回答
            if result.get("success"):
                memory.add_assistant_message(result.get("result", ""))

            # 6. 反思循环
            cycle_count = 0
            reflection_result = {"need_retry": False, "feedback": "无需修正"}
            while cycle_count < self.max_cycles:
                trace.step_start(f"reflection_cycle_{cycle_count + 1}")
                reflection_result = self.reflector.reflect(
                    user_input, plan, result, context, user_profile
                )
                trace.step_end(f"reflection_cycle_{cycle_count + 1}", reflection_result)

                if not reflection_result.get("need_retry"):
                    break

                logger.info(f"反思触发修正: {reflection_result.get('feedback')}")

                new_plan = reflection_result.get("new_plan")
                if new_plan:
                    trace.step_start("executor_retry")
                    plan = new_plan
                    result = self.executor.execute(plan, user_profile)
                    if result.get("success"):
                        memory.add_assistant_message(result.get("result", ""))
                    trace.step_end("executor_retry", result)

                cycle_count += 1

            # 7. 结束追踪
            trace.end()
            summary = trace.get_summary()

            # 8. 返回结果
            return {
                "success": result.get("success", False),
                "answer": result.get("result", "处理失败"),
                "action": plan.get("action", "unknown"),
                "reasoning": plan.get("reasoning", ""),
                "reflection": reflection_result.get("feedback", ""),
                "trace_id": trace.trace_id
            }

        except Exception as e:
            logger.error(f"Agent 循环异常: {e}")
            trace.status = "error"
            trace.end()
            return {
                "success": False,
                "answer": f"处理异常: {e}",
                "action": "error",
                "reasoning": "",
                "reflection": "",
                "trace_id": trace.trace_id if trace else None
            }