from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """所有工具的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称（唯一标识）"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（给 Planner 看的，用于决定是否调用）"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """参数定义（给 Planner 看的，告诉它需要什么参数）"""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行工具，返回结果"""
        pass