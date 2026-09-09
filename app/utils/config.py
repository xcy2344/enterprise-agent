import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Config:
    """项目配置类"""

    # ===== 大模型配置 =====
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    LLM_MODEL = "qwen-turbo"

    # ===== 向量存储配置 =====
    VECTOR_PERSIST_DIR = "./data/vectors"
    TOP_K = 3

    # ===== Embedding 配置 =====
    EMBEDDING_MODEL = "text-embedding-v2"
    EMBEDDING_DIMENSION = 1536

    # ===== 知识库配置 =====
    KNOWLEDGE_DIR = "./data/knowledge"

    @classmethod
    def validate(cls):
        """验证必要配置是否存在"""
        if not cls.DASHSCOPE_API_KEY:
            raise ValueError("请在 .env 文件中配置 DASHSCOPE_API_KEY")