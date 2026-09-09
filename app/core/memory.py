from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import os

class ShortTermMemory:
    """短期记忆：存储当前会话的对话历史"""
    
    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self.history: List[Dict[str, str]] = []
    
    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_turns * 2:
            self.history = self.history[-self.max_turns * 2:]
    
    def get_context(self) -> List[Dict[str, str]]:
        return self.history
    
    def clear(self):
        self.history = []


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