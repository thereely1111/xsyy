"""
向量数据库管理模块
使用 Chroma 存储和管理题目的 embedding 向量
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

# 加载环境变量
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# 全局变量
_chroma_client = None
_chroma_collection = None
_collection_name = "teachings"

def get_chroma_client() -> chromadb.Client:
    """获取或初始化 Chroma 客户端（单例模式）"""
    global _chroma_client
    if _chroma_client is None:
        # 使用持久化存储，数据保存在 backend/chroma_db 目录
        chroma_db_path = backend_dir / "chroma_db"
        chroma_db_path.mkdir(exist_ok=True)
        
        _chroma_client = chromadb.PersistentClient(
            path=str(chroma_db_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
    return _chroma_client


def get_chroma_collection() -> chromadb.Collection:
    """获取或创建 Chroma 集合（单例模式）"""
    global _chroma_collection
    if _chroma_collection is None:
        client = get_chroma_client()
        try:
            # 尝试获取现有集合
            _chroma_collection = client.get_collection(name=_collection_name)
        except Exception:
            # 如果不存在，创建新集合
            _chroma_collection = client.create_collection(
                name=_collection_name,
                metadata={"hnsw:space": "cosine"},  # 使用余弦相似度
                embedding_function=None  # 我们手动提供 embedding
            )
    return _chroma_collection


def add_teaching_embedding(
    task_id: str,
    question: str,
    embedding: List[float],
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    添加题目的 embedding 到向量数据库
    
    Args:
        task_id: 题目 ID
        question: 题目文本
        embedding: embedding 向量
        metadata: 可选的元数据（如 title, main_tag 等）
        
    Returns:
        是否成功添加
    """
    try:
        collection = get_chroma_collection()
        
        # 准备元数据（Chroma 只支持 str, int, float, bool, None）
        doc_metadata = {}
        if metadata:
            for key, value in metadata.items():
                if value is None:
                    continue
                elif isinstance(value, (str, int, float, bool)):
                    doc_metadata[key] = value
                elif isinstance(value, list):
                    # 将列表转换为逗号分隔的字符串
                    doc_metadata[key] = ", ".join(str(item) for item in value)
                elif isinstance(value, dict):
                    # 将字典转换为 JSON 字符串
                    import json
                    doc_metadata[key] = json.dumps(value, ensure_ascii=False)
                else:
                    # 其他类型转换为字符串
                    doc_metadata[key] = str(value)
        
        doc_metadata["question"] = question
        
        # 添加到集合
        collection.add(
            ids=[task_id],
            embeddings=[embedding],
            documents=[question],
            metadatas=[doc_metadata]
        )
        return True
    except Exception as e:
        print(f"添加 embedding 到向量数据库失败: {e}", file=sys.stderr)
        return False


def query_similar_teachings(
    query_embedding: List[float],
    n_results: int = 10,
    exclude_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    查询相似的题目
    
    Args:
        query_embedding: 查询的 embedding 向量
        n_results: 返回的结果数量
        exclude_ids: 要排除的 task_id 列表（例如当前题目本身）
        
    Returns:
        相似题目列表，每个元素包含：
        - id: task_id
        - distance: 距离（越小越相似）
        - metadata: 元数据
        - document: 题目文本
    """
    try:
        collection = get_chroma_collection()
        
        # 构建查询
        where = None
        if exclude_ids:
            # Chroma 不支持直接排除，我们需要查询更多结果然后过滤
            n_results = n_results + len(exclude_ids) if exclude_ids else n_results
        
        # 执行查询
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["metadatas", "documents", "distances"]
        )
        
        # 处理结果
        similar_items = []
        if results.get("ids") is not None and len(results["ids"]) > 0 and len(results["ids"][0]) > 0:
            for i, task_id in enumerate(results["ids"][0]):
                # 排除指定的 ID
                if exclude_ids and task_id in exclude_ids:
                    continue
                
                similar_items.append({
                    "id": task_id,
                    "distance": results["distances"][0][i],
                    "similarity": 1 - results["distances"][0][i],  # 转换为相似度（1 - 距离）
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "document": results["documents"][0][i] if results["documents"] else ""
                })
                
                # 如果已经达到所需数量，停止
                if len(similar_items) >= n_results:
                    break
        
        return similar_items
    except Exception as e:
        print(f"查询相似题目失败: {e}", file=sys.stderr)
        return []


def get_teaching_embedding(task_id: str) -> Optional[List[float]]:
    """
    获取指定题目的 embedding
    
    Args:
        task_id: 题目 ID
        
    Returns:
        embedding 向量，如果不存在返回 None
    """
    try:
        collection = get_chroma_collection()
        results = collection.get(
            ids=[task_id],
            include=["embeddings"]
        )
        
        # 检查 embeddings 是否存在且不为空
        if results.get("embeddings") is not None and len(results["embeddings"]) > 0:
            return results["embeddings"][0]
        return None
    except Exception as e:
        print(f"获取 embedding 失败: {e}", file=sys.stderr)
        return None


def delete_teaching_embedding(task_id: str) -> bool:
    """
    删除指定题目的 embedding
    
    Args:
        task_id: 题目 ID
        
    Returns:
        是否成功删除
    """
    try:
        collection = get_chroma_collection()
        collection.delete(ids=[task_id])
        return True
    except Exception as e:
        print(f"删除 embedding 失败: {e}", file=sys.stderr)
        return False


def update_teaching_embedding(
    task_id: str,
    question: str,
    embedding: List[float],
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    更新题目的 embedding（先删除再添加）
    
    Args:
        task_id: 题目 ID
        question: 题目文本
        embedding: embedding 向量
        metadata: 可选的元数据
        
    Returns:
        是否成功更新
    """
    # 先删除旧的
    delete_teaching_embedding(task_id)
    # 再添加新的
    return add_teaching_embedding(task_id, question, embedding, metadata)


def count_teachings() -> int:
    """
    获取向量数据库中的题目数量
    
    Returns:
        题目数量
    """
    try:
        collection = get_chroma_collection()
        return collection.count()
    except Exception as e:
        print(f"获取题目数量失败: {e}", file=sys.stderr)
        return 0

