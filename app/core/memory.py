from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import os

from app.utils.config import Config
from app.utils.llm import call_llm_with_retry
from app.utils.logger import logger

# 摘要生成提示词：把较早的多轮对话压缩成一段不超过 100 字的摘要
SUMMARY_PROMPT_TEMPLATE = """请把下面的对话压缩成一段不超过 100 字的摘要，用于后续对话的上下文。

要求：
1. 保留关键事实：用户提到的偏好、身份信息、已确认的结论、待办事项
2. 不要编造对话中没有出现过的内容
3. 只输出摘要正文，不要输出“摘要：”之类的前缀

{existing}对话内容：
{conversation}

摘要："""

# 摘要内容的最大字数
SUMMARY_MAX_CHARS = 100

# 历史对话摘要条目的前缀（摘要以 role="system" 的形式保存在 history 开头）
SUMMARY_PREFIX = "历史对话摘要："

# 触发压缩时压缩掉的轮数（1 轮 = 用户 1 条 + 助手 1 条消息）
SUMMARY_COMPRESS_TURNS = 5


class ShortTermMemory:
    """短期记忆：存储当前会话的对话历史

    对话轮数达到 SUMMARY_TRIGGER_TURNS 时，把最早的 SUMMARY_COMPRESS_TURNS 轮对话
    交给大模型压缩成一段摘要，以 role="system" 的消息插到 history 开头，
    避免早期对话被直接丢弃导致历史信息完全丢失。
    """

    def __init__(self, max_turns: int = None):
        self.max_turns = max_turns or Config.MEMORY_MAX_TURNS
        self.history: List[Dict[str, str]] = []

    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        self._compress_history()

    def get_context(self) -> List[Dict[str, str]]:
        return self.history

    def clear(self):
        self.history = []

    def _conversation(self) -> List[Dict[str, str]]:
        """取出纯对话记录（摘要等 system 消息不计入轮数）"""
        return [m for m in self.history if m.get("role") != "system"]

    def _current_summary(self) -> str:
        """取出已有的历史摘要正文（没有则返回空串）"""
        for message in self.history:
            if message.get("role") == "system":
                content = message.get("content", "")
                if content.startswith(SUMMARY_PREFIX):
                    return content[len(SUMMARY_PREFIX):]
                return content
        return ""

    def _compress_history(self):
        """对话轮数达到阈值时，把最早的若干轮对话压缩成摘要"""
        conversation = self._conversation()

        # 每轮对话包含 user + assistant 两条消息，不足阈值直接返回
        if len(conversation) // 2 < Config.SUMMARY_TRIGGER_TURNS:
            return

        oldest = conversation[:SUMMARY_COMPRESS_TURNS * 2]
        remaining = conversation[SUMMARY_COMPRESS_TURNS * 2:]

        summary = self._summarize(oldest, self._current_summary())
        if not summary:
            # 摘要生成失败：回退到原来的截断逻辑（直接丢弃最早的对话），不影响主流程
            logger.warning(
                f"历史对话摘要生成失败，回退到截断逻辑：丢弃最早对话，保留最近 {self.max_turns} 轮"
            )
            self.history = self.history[-self.max_turns * 2:]
            return

        # 保险：压缩后仍超过上限时，只保留最近 max_turns 轮（从 user 消息开始，保证问答成对）
        max_entries = self.max_turns * 2
        if len(remaining) > max_entries:
            remaining = remaining[-max_entries:]
            if remaining and remaining[0].get("role") != "user":
                remaining = remaining[1:]

        self.history = [{"role": "system", "content": SUMMARY_PREFIX + summary}] + remaining
        logger.info(
            f"历史对话已压缩：摘要 {len(summary)} 字，保留最近 {len(remaining) // 2} 轮对话"
        )

    def _summarize(self, messages: List[Dict[str, str]], existing_summary: str = "") -> Optional[str]:
        """调用大模型把若干轮对话压缩成摘要，失败返回 None"""
        conversation = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}：{m.get('content', '')}"
            for m in messages
        )
        existing = ""
        if existing_summary:
            existing = f"已有摘要（需要与新对话合并）：\n{existing_summary}\n\n"

        prompt = SUMMARY_PROMPT_TEMPLATE.format(existing=existing, conversation=conversation)

        summary = call_llm_with_retry(prompt=prompt, model=Config.LLM_MODEL)
        if not summary:
            return None

        summary = summary.strip()
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = self._truncate_summary(summary)
        return summary

    @staticmethod
    def _truncate_summary(summary: str) -> str:
        """摘要超长时优先在句末标点处截断，避免被拦腰截断"""
        head = summary[:SUMMARY_MAX_CHARS]
        for punct in ("。", "；", "！", "？", "\n"):
            cut = head.rfind(punct)
            if cut >= SUMMARY_MAX_CHARS // 2:
                return head[:cut + 1]
        return head


class LongTermMemory:
    """长期记忆：跨会话记住用户信息"""
    
    def __init__(self, storage_path: str = "./data/memory/user_profiles.json"):
        self.storage_path = storage_path
        self.profiles: Dict[str, Dict] = {}
        self._load()
    
    def _load(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        if os.path.exists(self.storage_path):
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                self.profiles = json.load(f)
    
    def _save(self):
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.profiles, f, ensure_ascii=False, indent=2)
    
    def get_user(self, user_id: str) -> Dict:
        if user_id not in self.profiles:
            self.profiles[user_id] = {
                "preferences": {},
                "history_queries": [],
                "last_active": datetime.now().isoformat()
            }
        return self.profiles[user_id]
    
    def update_user(self, user_id: str, data: Dict):
        user = self.get_user(user_id)
        for key, value in data.items():
            if key == "preferences":
                user["preferences"].update(value)
            elif key == "query":
                user["history_queries"].append({
                    "query": value,
                    "timestamp": datetime.now().isoformat()
                })
                if len(user["history_queries"]) > 50:
                    user["history_queries"] = user["history_queries"][-50:]
        user["last_active"] = datetime.now().isoformat()
        self._save()


class Memory:
    """统一记忆接口"""
    
    def __init__(self, user_id: Optional[str] = None):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self.user_id = user_id or "default_user"
    
    def add_user_message(self, content: str):
        self.short_term.add("user", content)
        self.long_term.update_user(self.user_id, {"query": content})
    
    def add_assistant_message(self, content: str):
        self.short_term.add("assistant", content)
    
    def get_context(self) -> List[Dict[str, str]]:
        return self.short_term.get_context()
    
    def get_user_profile(self) -> Dict:
        return self.long_term.get_user(self.user_id)
    
    def update_preferences(self, preferences: Dict):
        self.long_term.update_user(self.user_id, {"preferences": preferences})
