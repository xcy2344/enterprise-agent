import threading
from collections import OrderedDict
from typing import Any, Dict, Iterator, List

from app.core.memory import Memory
from app.core.planner import Planner
from app.core.executor import Executor
from app.core.reflector import Reflector
from app.core.aggregator import Aggregator
from app.core.rag import rag_service
from app.utils.config import Config
from app.utils.llm import LLM_FALLBACK_REPLY
from app.utils.logger import logger
from app.utils.observability import start_trace, get_current_trace, end_trace


class AgentLoop:
    """Agent 核心循环（含反思机制 + 可观测追踪）"""

    def __init__(self):
        self.planner = Planner()
        self.executor = Executor()
        self.reflector = Reflector()
        self.aggregator = Aggregator()
        self.max_cycles = 3
        # 会话级短期记忆缓存：{user_id: Memory}，用 OrderedDict 维护 LRU 顺序
        self._session_cache: "OrderedDict[str, Memory]" = OrderedDict()
        self._session_lock = threading.Lock()
        self._session_cache_max_size = Config.SESSION_CACHE_MAX_SIZE

    def _get_or_create_memory(self, user_id: str) -> Memory:
        """
        取出（或新建）该用户的会话级 Memory，使短期记忆（含历史摘要）能跨请求累积

        - 命中缓存：把该会话移到 LRU 末尾后复用
        - 未命中缓存：新建 Memory 并放入缓存
        - 缓存超过 SESSION_CACHE_MAX_SIZE：淘汰最久未使用的会话（其短期记忆随之丢弃，
          长期记忆已落盘，不受影响）
        - 读写在 threading.Lock 保护下进行，兼容 FastAPI 线程池的并发调用
        """
        with self._session_lock:
            memory = self._session_cache.get(user_id)
            if memory is None:
                memory = Memory(user_id)
                self._session_cache[user_id] = memory
                while len(self._session_cache) > self._session_cache_max_size:
                    evicted_id, _ = self._session_cache.popitem(last=False)
                    logger.info(
                        f"会话缓存已达上限 {self._session_cache_max_size}，"
                        f"淘汰最久未使用的会话: user_id={evicted_id}"
                    )
            else:
                self._session_cache.move_to_end(user_id)
        return memory

    def run(self, user_input: str, user_id: str = "default_user") -> Dict[str, Any]:
        # 1. 启动追踪
        trace = start_trace(user_id, user_input)
        logger.info(f"Agent 开始处理: user_id={user_id}, input={user_input}")

        try:
            # 2. 加载记忆
            trace.step_start("memory_load")
            memory = self._get_or_create_memory(user_id)
            memory.add_user_message(user_input)
            context = memory.get_context()
            user_profile = memory.get_user_profile()
            trace.step_end("memory_load", {"context_len": len(context), "profile": user_profile})

            # 3. Planner 决策
            trace.step_start("planner")
            plan = self.planner.plan(user_input, context, user_profile)
            trace.step_end("planner", plan)

            # 大模型不可用（重试后仍失败）：直接返回降级回答，不再往下走
            if plan is None:
                logger.error("Planner 未返回有效计划（大模型不可用），返回降级回答")
                trace.end()
                return {
                    "success": False,
                    "answer": LLM_FALLBACK_REPLY,
                    "action": "degraded",
                    "reasoning": "大模型调用失败，已降级",
                    "reflection": "服务不可用，跳过反思",
                    "trace_id": trace.trace_id
                }

            logger.info(f"Planner 决策: {plan}")

            # 4. 多步任务：逐个执行子任务后汇总成一个回答
            if plan.get("mode") == "multi_step":
                answer = self._execute_subtasks(
                    user_input, plan, memory, user_profile, context, trace
                )
                memory.add_assistant_message(answer)
                trace.end()
                logger.info(f"多步任务完成，子任务数: {len(plan.get('subtasks') or [])}")
                return {
                    "success": True,
                    "answer": answer,
                    "action": "multi_step",
                    "reasoning": plan.get("reasoning", ""),
                    "reflection": "多步任务，已汇总各子任务结果",
                    "trace_id": trace.trace_id
                }

            # 5. Executor 执行
            trace.step_start("executor")
            result = self.executor.execute(plan, user_profile, context)
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
                    result = self.executor.execute(plan, user_profile, context)
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

    def _execute_subtasks(
        self,
        user_input: str,
        plan: Dict[str, Any],
        memory: Memory,
        user_profile: Dict,
        memory_context: List[Dict],
        trace
    ) -> str:
        """
        顺序执行多步任务的子任务，并汇总成一个回答

        - 每个子任务交给 Executor 正常执行（含工具调度与未知动作兜底），Trace 里逐个记录
        - 单个子任务异常不会中断整体流程，会标记为失败后继续执行剩余子任务
        - 全部子任务失败时由 Aggregator 返回友好提示，不抛异常、不返回内部错误信息
        - 子任务里识别到的用户偏好同样落库，与单步链路保持一致
        """
        subtasks = plan.get("subtasks") or []
        results: List[Dict[str, Any]] = []

        for index, subtask in enumerate(subtasks, 1):
            step = subtask.get("step", index)
            action = subtask.get("action", "")
            trace.step_start(f"subtask_{step}")

            try:
                result = self.executor.execute(
                    {"action": action, "params": subtask.get("params") or {}},
                    user_profile,
                    memory_context
                )
            except Exception as e:
                logger.error(f"子任务 {step} 执行异常: {e}")
                result = {"success": False, "result": f"子任务执行异常: {e}", "action": action}

            if result.get("need_save") and result.get("preferences"):
                memory.update_preferences(result["preferences"])
                logger.info(f"子任务 {step} 已存储用户偏好: {result['preferences']}")

            results.append({
                "step": step,
                "action": action,
                "reason": subtask.get("reason", ""),
                "success": bool(result.get("success")),
                "result": result.get("result", "")
            })
            logger.info(
                f"子任务 {step}/{len(subtasks)} 完成: action={action}, "
                f"success={result.get('success')}, result={str(result.get('result'))[:80]}"
            )
            trace.step_end(f"subtask_{step}", {"action": action, "success": bool(result.get("success"))})

        trace.step_start("aggregate")
        answer = self.aggregator.aggregate(user_input, results)
        trace.step_end("aggregate", {"answer_len": len(answer)})
        return answer

    def run_stream(self, user_input: str, user_id: str = "default_user") -> Iterator[str]:
        """
        流式处理用户输入，逐块 yield 回答文本

        - Planner 降级（大模型不可用）：yield 降级话术
        - action == "rag_query"：调用 RAG 流式方法，边生成边 yield
        - 其他 action：正常执行后一次性 yield 完整回答

        说明：流式链路不做反思重试（避免客户端长时间无输出），
        记忆读写、Trace 记录与非流式链路保持一致。
        """
        trace = start_trace(user_id, user_input)
        logger.info(f"Agent 开始流式处理: user_id={user_id}, input={user_input}")

        try:
            # 1. 加载记忆
            trace.step_start("memory_load")
            memory = self._get_or_create_memory(user_id)
            memory.add_user_message(user_input)
            context = memory.get_context()
            user_profile = memory.get_user_profile()
            trace.step_end("memory_load", {"context_len": len(context), "profile": user_profile})

            # 2. Planner 决策（规则层 + 大模型）
            trace.step_start("planner")
            plan = self.planner.plan(user_input, context, user_profile)
            trace.step_end("planner", plan)

            # 3. 大模型不可用：降级
            if plan is None:
                logger.error("Planner 未返回有效计划（大模型不可用），返回降级回答")
                yield LLM_FALLBACK_REPLY
                return

            logger.info(f"Planner 决策: {plan}")

            # 4. 多步任务：逐个执行子任务后汇总，汇总结果一次性下发
            if plan.get("mode") == "multi_step":
                answer = self._execute_subtasks(
                    user_input, plan, memory, user_profile, context, trace
                )
                if answer:
                    memory.add_assistant_message(answer)
                logger.info(f"多步任务（流式链路）完成，子任务数: {len(plan.get('subtasks') or [])}")
                yield answer
                return

            # 5. RAG 查询：流式返回
            if plan.get("action") == "rag_query":
                question = plan.get("params", {}).get("question") or user_input
                logger.info(f"流式执行 RAG 查询: {question}")
                trace.step_start("rag_stream")
                answer = ""
                for chunk in rag_service.answer_stream(question, memory_context=context):
                    answer += chunk
                    yield chunk
                trace.step_end("rag_stream", {"answer_len": len(answer)})
                if answer:
                    memory.add_assistant_message(answer)
                return

            # 5. 其他 action：复用 Executor 执行后一次性返回完整回答
            trace.step_start("executor")
            result = self.executor.execute(plan, user_profile, context)
            trace.step_end("executor", result)

            answer = result.get("result", "处理失败")

            # 保存偏好（与非流式链路保持一致）
            if result.get("need_save"):
                prefs = result.get("preferences", {})
                if prefs:
                    memory.update_preferences(prefs)
                    logger.info(f"已存储用户偏好: {prefs}")
                    answer = f"已记录您的偏好: {prefs}"

            if result.get("success"):
                memory.add_assistant_message(answer)

            yield answer

        except Exception as e:
            logger.error(f"Agent 流式循环异常: {e}")
            trace.status = "error"
            yield LLM_FALLBACK_REPLY
        finally:
            trace.end()
