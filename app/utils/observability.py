import time
import uuid
from typing import Dict, Any, List
from datetime import datetime
from app.utils.logger import logger


class Trace:
    """全链路追踪：记录每一步的输入、输出、耗时"""

    def __init__(self, user_id: str, user_input: str):
        self.trace_id = str(uuid.uuid4())[:8]
        self.user_id = user_id
        self.user_input = user_input
        self.steps: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.status = "running"

    def step_start(self, step_name: str, data: Dict[str, Any] = None):
        """记录步骤开始"""
        self.steps.append({
            "step": step_name,
            "input": data,
            "start": time.time(),
            "status": "running"
        })
        logger.info(f"[Trace {self.trace_id}] {step_name} 开始")

    def step_end(self, step_name: str, output: Dict[str, Any] = None):
        """记录步骤结束"""
        for step in reversed(self.steps):
            if step["step"] == step_name and step["status"] == "running":
                step["end"] = time.time()
                step["duration"] = round((step["end"] - step["start"]) * 1000, 2)
                step["output"] = output
                step["status"] = "done"
                logger.info(f"[Trace {self.trace_id}] {step_name} 完成，耗时 {step['duration']}ms")
                break

    def end(self):
        """结束追踪"""
        self.status = "done"
        self.end_time = time.time()
        self.total_duration = round((self.end_time - self.start_time) * 1000, 2)
        logger.info(f"[Trace {self.trace_id}] 总耗时 {self.total_duration}ms")

    def get_summary(self) -> Dict[str, Any]:
        """获取追踪摘要"""
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "total_duration_ms": self.total_duration,
            "steps": [
                {
                    "step": s["step"],
                    "duration_ms": s.get("duration", 0),
                    "input": s.get("input"),
                    "output": s.get("output")
                }
                for s in self.steps
            ],
            "status": self.status
        }


# 当前追踪上下文（简单实现，生产环境需要按请求隔离）
_current_trace: Trace = None


def start_trace(user_id: str, user_input: str) -> Trace:
    global _current_trace
    _current_trace = Trace(user_id, user_input)
    return _current_trace


def get_current_trace() -> Trace:
    return _current_trace


def end_trace():
    if _current_trace:
        _current_trace.end()
        return _current_trace.get_summary()
    return None