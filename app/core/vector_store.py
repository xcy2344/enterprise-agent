import os
import json
import numpy as np
import faiss
from typing import List, Dict, Any
from app.utils.config import Config
from app.utils.logger import logger
from app.utils.embedding import embedding_client


class VectorStore:
    """
    向量存储 + 检索
    底层用 FAISS，同时把原文和元数据用 JSON 存下来
    """

    def __init__(self):
        self.dimension = Config.EMBEDDING_DIMENSION
        self.persist_dir = Config.VECTOR_PERSIST_DIR
        self.index_path = os.path.join(self.persist_dir, "index.faiss")
        self.metadata_path = os.path.join(self.persist_dir, "metadata.json")

        # 确保目录存在
        os.makedirs(self.persist_dir, exist_ok=True)

        # 加载已有的数据，或创建新数据
        self.index, self.metadata = self._load_or_create()

    def _load_or_create(self):
        """
        从磁盘加载已有的 FAISS 索引和元数据，
        如果文件不存在，则创建新的空索引
        """
        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            try:
                index = faiss.read_index(self.index_path)
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                logger.info(f"加载已有向量库，共 {len(metadata)} 条记录")
                return index, metadata
            except Exception as e:
                logger.warning(f"加载向量库失败: {e}，将重新创建")
                return self._create_empty()
        else:
            logger.info("创建新的向量库")
            return self._create_empty()

    def _create_empty(self):
        """创建一个空的 FAISS 索引和空元数据列表"""
        index = faiss.IndexFlatL2(self.dimension)
        metadata = []
        return index, metadata

    def add(self, texts: List[str], sources: List[str] = None):
        """
        向向量库添加文本

        参数：
            texts: 文本列表，每个元素是一段知识文档
            sources: 来源列表，标注每段文本来自哪里
        """
        if not texts:
            return

        if sources is None:
            sources = ["unknown"] * len(texts)

        # 调用 Embedding 接口，把文本转成向量
        vectors = embedding_client.encode(texts)
        if vectors is None:
            logger.error("生成向量失败")
            return

        # 统一转为二维数组（FAISS 要求）
        if isinstance(vectors, list) and len(vectors) > 0:
            if isinstance(vectors[0], list):
                vectors_array = np.array(vectors, dtype=np.float32)
            else:
                vectors_array = np.array([vectors], dtype=np.float32)
        else:
            logger.error("向量格式异常")
            return

        # 存入 FAISS
        start_idx = len(self.metadata)
        self.index.add(vectors_array)

        # 存元数据（原文 + 来源）
        for i, text in enumerate(texts):
            self.metadata.append({
                "id": start_idx + i,
                "text": text,
                "source": sources[i] if i < len(sources) else "unknown"
            })

        # 保存到磁盘
        self._save()
        logger.info(f"添加 {len(texts)} 条记录，当前共 {len(self.metadata)} 条")

    def search(self, query: str, top_k: int = None) -> List[Dict[str, Any]]:
        """
        检索与 query 最相似的 top_k 条文本

        参数：
            query: 用户问题
            top_k: 返回结果数量，默认取 Config.TOP_K

        返回：
            列表，每个元素包含 text、source、score
        """
        if top_k is None:
            top_k = Config.TOP_K

        # 如果索引为空，直接返回空结果
        if self.index.ntotal == 0:
            return []

        # 把用户问题转成向量
        query_vec = embedding_client.encode(query)
        if query_vec is None:
            return []

        # 转为二维数组
        query_vec = np.array([query_vec], dtype=np.float32)

        # FAISS 搜索
        distances, indices = self.index.search(query_vec, min(top_k, self.index.ntotal))

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.metadata):
                results.append({
                    "text": self.metadata[idx]["text"],
                    "source": self.metadata[idx]["source"],
                    "score": float(distances[0][i])
                })

        return results

    def _save(self):
        """
        将索引和元数据保存到磁盘
        """
        faiss.write_index(self.index, self.index_path)
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def count(self) -> int:
        """返回向量库中的记录总数"""
        return self.index.ntotal


# 全局实例
vector_store = VectorStore()