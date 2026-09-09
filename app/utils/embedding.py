import requests
from typing import List, Union
from app.utils.config import Config
from app.utils.logger import logger


class EmbeddingClient:
    """
    调用百炼 Embedding API，将文本转换成向量
    """

    def __init__(self):
        self.api_key = Config.DASHSCOPE_API_KEY
        self.url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
        self.model = Config.EMBEDDING_MODEL

    def encode(self, texts: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        if isinstance(texts, str):
            single_input = True
            input_texts = [texts]
        else:
            single_input = False
            input_texts = texts

        if not input_texts:
            logger.warning("传入的文本为空")
            return [] if not single_input else None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "input": {"texts": input_texts}
        }

        try:
            response = requests.post(
                self.url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                embeddings = [item["embedding"] for item in result["output"]["embeddings"]]

                if single_input:
                    return embeddings[0]
                return embeddings
            else:
                logger.error(f"Embedding API 请求失败: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.Timeout:
            logger.error("Embedding API 请求超时")
            return None
        except Exception as e:
            logger.error(f"Embedding API 异常: {e}")
            return None


embedding_client = EmbeddingClient()