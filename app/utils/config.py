import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Config:
    """项目配置类"""

    # ===== 大模型配置 =====
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    LLM_MODEL = "qwen-turbo"

    # ===== 大模型调用重试配置 =====
    # 首次调用失败后最多重试次数（总调用次数 = 1 + MAX_RETRIES）
    MAX_RETRIES = 2
    # 重试基础间隔（秒），按指数退避：第 n 次重试前等待 RETRY_DELAY * 2 ** (n - 1)，即 1、2、4...
    RETRY_DELAY = 1

    # ===== 向量存储配置 =====
    VECTOR_PERSIST_DIR = "./data/vectors"
    TOP_K = 3

    # ===== 短期记忆配置 =====
    # 短期记忆最多保留的对话轮数（1 轮 = 用户 1 条 + 助手 1 条消息）
    MEMORY_MAX_TURNS = 10
    # 触发摘要压缩的对话轮数阈值：对话轮数达到该值时，把最早的若干轮对话交给大模型压缩成一段摘要，
    # 摘要以 role="system" 的消息保留在历史开头，避免早期对话被直接丢弃，并提升多轮指代能力。
    SUMMARY_TRIGGER_TURNS = 15

    # ===== 会话缓存配置 =====
    # AgentLoop 中按 user_id 缓存的会话级短期记忆（含历史摘要）上限；
    # 超过后淘汰最久未使用的会话，避免服务长时间运行导致内存无限增长。
    # 短期记忆只存在内存中，服务重启即清空；长期记忆（user_profiles.json）仍照常落盘。
    SESSION_CACHE_MAX_SIZE = 100

    # ===== 检索质量评估配置 =====
    # 检索结果中的 score 是余弦相似度（0~1，越大越相关）。
    # 最高相似度低于该阈值时，判定为知识库外的问题，直接返回兜底提示、不调用大模型，避免编造答案。
    # 实测（text-embedding-v2 + 当前知识库）：知识库内问题最高相似度约 0.39~0.77，
    # 知识库外问题（如今天天气怎么样）最高相似度约 0.05~0.24，故取两者之间偏安全的值。
    RAG_SCORE_THRESHOLD = 0.30

    # ===== 任务分解配置 =====
    # 是否开启多步任务分解：开启后，包含“对比 / 然后 / 分别 / 以及”这类多诉求的问题会先被
    # TaskDecomposer 拆成子任务，逐个执行后再由 Aggregator 汇总成一个完整回答。
    ENABLE_TASK_DECOMPOSITION = True
    # 单个问题最多拆解的子任务数量，防止任务被拆得过碎导致耗时和 Token 成本失控
    MAX_SUBTASKS = 5

    # ===== MCP 服务器配置 =====
    # MCP 服务器的 Bearer Token（从 .env 读取）；为空时跳过鉴权，仅用于本地开发与演示。
    MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN")

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
