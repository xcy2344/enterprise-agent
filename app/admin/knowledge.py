from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.vector_store import vector_store
from app.utils.logger import logger
import os
import json

router = APIRouter()


class KnowledgeItem(BaseModel):
    text: str
    source: Optional[str] = "manual"


class KnowledgeResponse(BaseModel):
    success: bool
    message: str
    total: int


@router.post("/knowledge/add", response_model=KnowledgeResponse)
async def add_knowledge(item: KnowledgeItem):
    """增量添加知识条目"""
    try:
        texts = [item.text]
        sources = [item.source]
        vector_store.add(texts, sources)
        logger.info(f"增量添加知识: {item.text[:50]}...")
        return KnowledgeResponse(
            success=True,
            message="知识添加成功",
            total=vector_store.count()
        )
    except Exception as e:
        logger.error(f"添加知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge/delete/{doc_id}")
async def delete_knowledge(doc_id: int):
    """删除指定知识条目（按ID）"""
    try:
        # 读取当前 metadata
        metadata_path = vector_store.metadata_path
        if not os.path.exists(metadata_path):
            raise HTTPException(status_code=404, detail="向量库不存在")

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # 移除指定 ID
        new_metadata = [item for item in metadata if item["id"] != doc_id]
        if len(new_metadata) == len(metadata):
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {doc_id} 的知识条目")

        # 重新构建索引（简化处理：全量重建）
        # 注意：生产环境需要用更高效的方法，这里为简化直接重建
        texts = [item["text"] for item in new_metadata]
        sources = [item["source"] for item in new_metadata]

        # 清空并重建
        vector_store.metadata = []
        vector_store.index = vector_store._create_empty()[0]
        vector_store._save()

        if texts:
            vector_store.add(texts, sources)

        logger.info(f"删除知识条目: ID={doc_id}")
        return {"success": True, "message": f"已删除 ID 为 {doc_id} 的知识条目", "total": vector_store.count()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge/list")
async def list_knowledge():
    """列出所有知识条目"""
    try:
        metadata_path = vector_store.metadata_path
        if not os.path.exists(metadata_path):
            return {"items": [], "total": 0}

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        return {"items": metadata, "total": len(metadata)}
    except Exception as e:
        logger.error(f"列出知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))