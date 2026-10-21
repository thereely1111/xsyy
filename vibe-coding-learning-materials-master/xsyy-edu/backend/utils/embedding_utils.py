"""
题目语义相似度计算工具
使用 sentence-transformers 本地模型将题目文本转换为向量，并使用 Chroma 向量数据库进行相似度搜索
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
from sentence_transformers import SentenceTransformer
try:
    from alibabacloud_tea_openapi import models as open_api_models  # type: ignore
    from alibabacloud_searchplat20240529.client import Client as SearchPlatClient  # type: ignore
    from alibabacloud_searchplat20240529 import models as search_models  # type: ignore
except ImportError:
    open_api_models = None
    SearchPlatClient = None
    search_models = None

from dotenv import load_dotenv
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 向量数据库模块（延迟导入，避免循环依赖）

# 加载环境变量
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# 初始化模型（延迟加载）
_embedding_model = None
_model_loading = False
_model_loading_lock = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1)

def _normalize_embeddings(raw) -> List[List[float]]:
    """将 OpenSearch 返回的多种格式归一化为 List[List[float]]"""
    if raw is None:
        return []
    # 如果已经是列表且元素是数字列表
    if isinstance(raw, list):
        if not raw:
            return []
        first = raw[0]
        if isinstance(first, (list, tuple)):
            return [list(map(float, x)) for x in raw]
        # 如果是对象列表，尝试常见属性
        if hasattr(first, "embedding"):
            return [list(map(float, getattr(x, "embedding"))) for x in raw]
        if hasattr(first, "embeddings"):
            return [list(map(float, getattr(x, "embeddings"))) for x in raw]
        if hasattr(first, "vector"):
            return [list(map(float, getattr(x, "vector"))) for x in raw]
    # 字典或具备属性的情况
    if isinstance(raw, dict):
        if "embeddings" in raw:
            return _normalize_embeddings(raw["embeddings"])
        if "embedding" in raw:
            return _normalize_embeddings(raw["embedding"])
        if "vector" in raw:
            return _normalize_embeddings(raw["vector"])
    # 对象带属性
    for attr in ["embeddings", "embedding", "vector", "output", "result"]:
        if hasattr(raw, attr):
            return _normalize_embeddings(getattr(raw, attr))
    raise RuntimeError(f"无法解析 embeddings 字段，返回结构: {raw}")


def _call_aliyun_embedding(texts: List[str]) -> List[List[float]]:
    """调用阿里云 OpenSearch 百炼版 ops-text-embedding-001 获取向量"""
    if open_api_models is None or SearchPlatClient is None or search_models is None:
        raise ImportError("alibabacloud-searchplat SDK 未安装，请先安装 alibabacloud_searchplat20240529 与 alibabacloud_tea_openapi")
    if not texts:
        return []

    api_key = os.getenv("OPENSEARCH_API_KEY")
    endpoint = os.getenv("OPENSEARCH_ENDPOINT", "")  # 填写：OpenSearch 实例域名
    app_group = os.getenv("OPENSEARCH_APP_GROUP", "default")
    model_name = os.getenv("OPENSEARCH_MODEL", "ops-text-embedding-001")
    input_type = os.getenv("OPENSEARCH_INPUT_TYPE", "document")
    protocol = os.getenv("OPENSEARCH_PROTOCOL", "https")

    if not api_key:
        return []  # 未配置 OPENSEARCH_API_KEY，静默返回空列表
    if not endpoint:
        raise RuntimeError("OPENSEARCH_ENDPOINT 未配置，请在 .env 中填写 OpenSearch 实例域名")

    config = open_api_models.Config(
        bearer_token=api_key,
        endpoint=endpoint,
        protocol=protocol,
    )
    client = SearchPlatClient(config=config)
    request = search_models.GetTextEmbeddingRequest(
        input=texts,
        input_type=input_type,
    )
    resp = client.get_text_embedding(app_group, model_name, request)

    # 返回结构兼容处理
    output = getattr(resp, "body", None) or getattr(resp, "output", None) or getattr(resp, "result", None) or resp
    embeddings = _normalize_embeddings(output)
    return embeddings


async def get_embedding_model() -> SentenceTransformer:
    """获取或初始化 embedding 模型（异步延迟初始化），改为使用阿里云百炼 API"""
    global _embedding_model, _model_loading
    
    if _embedding_model is not None:
        return _embedding_model
    
    if _model_loading:
        while _embedding_model is None:
            await asyncio.sleep(0.1)
        return _embedding_model
    
    async with _model_loading_lock:
        if _embedding_model is not None:
            return _embedding_model
        _model_loading = True
        try:
            if open_api_models is None or SearchPlatClient is None or search_models is None:
                raise ImportError("未安装 alibabacloud-searchplat SDK，请先 pip install alibabacloud_searchplat20240529 alibabacloud_tea_openapi")
            print("正在初始化阿里云 OpenSearch embedding 客户端 (ops-text-embedding-001)", file=sys.stderr)

            class AliyunEncoder:
                def encode(self, text, convert_to_numpy=True, **kwargs):
                    texts = [text] if isinstance(text, str) else list(text)
                    embeddings = _call_aliyun_embedding(texts)
                    if not embeddings:
                        return np.array([], dtype=np.float32)
                    arr = np.array(embeddings, dtype=np.float32)
                    if isinstance(text, str):
                        arr = arr[0]
                    if convert_to_numpy:
                        return arr
                    return arr.tolist()

            loop = asyncio.get_event_loop()
            _embedding_model = await loop.run_in_executor(_executor, lambda: AliyunEncoder())
            print("阿里云 OpenSearch embedding 初始化完成 (ops-text-embedding-001)", file=sys.stderr)
        except Exception as e:
            print(f"加载 embedding 模型失败: {e}", file=sys.stderr)
            _model_loading = False
            raise
        finally:
            _model_loading = False
    
    return _embedding_model


def get_embedding_model_sync() -> SentenceTransformer:
    """同步版本的模型获取（用于非异步上下文），改为使用阿里云百炼 API"""
    global _embedding_model
    if _embedding_model is None:
        if open_api_models is None or SearchPlatClient is None or search_models is None:
            raise ImportError("未安装 alibabacloud-searchplat SDK，请先 pip install alibabacloud_searchplat20240529 alibabacloud_tea_openapi")
        print("正在初始化阿里云 OpenSearch embedding 客户端 (ops-text-embedding-001)", file=sys.stderr)

        class AliyunEncoder:
            def encode(self, text, convert_to_numpy=True, **kwargs):
                texts = [text] if isinstance(text, str) else list(text)
                embeddings = _call_aliyun_embedding(texts)
                arr = np.array(embeddings, dtype=np.float32)
                if isinstance(text, str):
                    arr = arr[0]
                if convert_to_numpy:
                    return arr
                return arr.tolist()

        _embedding_model = AliyunEncoder()
        print("阿里云 OpenSearch embedding 初始化完成 (ops-text-embedding-001)", file=sys.stderr)
    return _embedding_model


async def get_question_embedding_async(question_text: str) -> Optional[List[float]]:
    """
    获取题目的 embedding 向量（异步版本）
    
    Args:
        question_text: 题目文本
        
    Returns:
        embedding 向量，如果失败返回 None
    """
    if not question_text or not question_text.strip():
        return None
    
    try:
        model = await get_embedding_model()
        # 阿里云接口本身是 IO 操作，直接调用 encode（内部会同步请求）
        embedding = model.encode(question_text.strip(), convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        print(f"获取 embedding 失败: {e}", file=sys.stderr)
        return None


def get_question_embedding(question_text: str) -> Optional[List[float]]:
    """
    获取题目的 embedding 向量（同步版本）
    
    Args:
        question_text: 题目文本
        
    Returns:
        embedding 向量，如果失败返回 None
    """
    if not question_text or not question_text.strip():
        return None
    
    try:
        model = get_embedding_model_sync()
        embedding = model.encode(question_text.strip(), convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        print(f"获取 embedding 失败: {e}", file=sys.stderr)
        return None


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    计算两个向量的余弦相似度
    
    Args:
        vec1: 第一个向量
        vec2: 第二个向量
        
    Returns:
        余弦相似度值（-1 到 1 之间，1 表示完全相同）
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    vec1_array = np.array(vec1)
    vec2_array = np.array(vec2)
    
    # 计算余弦相似度
    dot_product = np.dot(vec1_array, vec2_array)
    norm1 = np.linalg.norm(vec1_array)
    norm2 = np.linalg.norm(vec2_array)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return float(dot_product / (norm1 * norm2))


async def find_similar_questions_async(
    current_question: str,
    current_task_id: str,
    top_k: int = 10
) -> List[Tuple[str, float]]:
    """
    使用 Chroma 向量数据库找到与当前题目最相似的其他题目（异步版本）
    
    Args:
        current_question: 当前题目文本
        current_task_id: 当前题目的 task_id（用于排除）
        top_k: 返回最相似的 k 个题目
        
    Returns:
        相似题目列表，每个元素是 (task_id, similarity_score) 元组，按相似度降序排列
    """
    if not current_question or not current_question.strip():
        return []
    
    try:
        # 延迟导入向量数据库模块，避免循环依赖
        from utils.vector_db import (
            add_teaching_embedding,
            query_similar_teachings,
            get_teaching_embedding
        )
        
        # 获取当前题目的 embedding
        current_embedding = await get_question_embedding_async(current_question)
        if current_embedding is None or len(current_embedding) == 0:
            return []
        
        # 检查向量数据库中是否有当前题目的 embedding，如果没有则添加
        existing_embedding = get_teaching_embedding(current_task_id)
        if existing_embedding is None or len(existing_embedding) == 0:
            # 添加到向量数据库
            add_teaching_embedding(
                task_id=current_task_id,
                question=current_question,
                embedding=current_embedding
            )
        
        # 使用 Chroma 查询相似题目
        similar_items = query_similar_teachings(
            query_embedding=current_embedding,
            n_results=top_k,
            exclude_ids=[current_task_id]
        )
        
        # 转换为返回格式
        results = [(item["id"], item["similarity"]) for item in similar_items]
        return results
    except Exception as e:
        print(f"查询相似题目失败: {e}", file=sys.stderr)
        return []


def find_similar_questions(
    current_question: str,
    other_questions: List[Tuple[str, str]],  # List of (task_id, question_text)
    top_k: int = 10
) -> List[Tuple[str, float]]:
    """
    找到与当前题目最相似的其他题目（同步版本，兼容旧接口）
    
    注意：此函数仍使用批量计算方式，主要用于向后兼容。
    新的代码应该使用 find_similar_questions_async 和 Chroma 向量数据库。
    
    Args:
        current_question: 当前题目文本
        other_questions: 其他题目列表，每个元素是 (task_id, question_text) 元组
        top_k: 返回最相似的 k 个题目
        
    Returns:
        相似题目列表，每个元素是 (task_id, similarity_score) 元组，按相似度降序排列
    """
    if not current_question or not other_questions:
        return []
    
    try:
        model = get_embedding_model_sync()
        
        # 批量编码所有题目（更高效）
        all_questions = [current_question] + [q[1] for q in other_questions]
        all_embeddings = model.encode(all_questions, convert_to_numpy=True, show_progress_bar=False)
        
        current_embedding = all_embeddings[0]
        other_embeddings = all_embeddings[1:]
        
        # 使用 numpy 批量计算相似度（优化性能）
        current_norm = np.linalg.norm(current_embedding)
        other_norms = np.linalg.norm(other_embeddings, axis=1)
        dot_products = np.dot(other_embeddings, current_embedding)
        similarities = dot_products / (other_norms * current_norm)
        
        # 创建结果列表并排序
        results = [
            (task_id, float(similarity))
            for (task_id, _), similarity in zip(other_questions, similarities)
        ]
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    except Exception as e:
        print(f"计算相似度失败: {e}", file=sys.stderr)
        return []


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("开始测试 embedding_utils 模块")
    print("=" * 60)
    
    # 测试 1: 获取单个题目的 embedding
    print("\n[测试 1] 获取单个题目的 embedding")
    test_question = "求解方程 x^2 + 5x + 6 = 0"
    embedding = get_question_embedding(test_question)
    if embedding:
        print(f"✓ 成功获取 embedding，向量维度: {len(embedding)}")
        print(f"  前 5 个值: {embedding[:5]}")
    else:
        print("✗ 获取 embedding 失败")
        sys.exit(1)
    
    # 测试 2: 计算余弦相似度
    print("\n[测试 2] 计算余弦相似度")
    question1 = "求解方程 x^2 + 5x + 6 = 0"
    question2 = "解方程 x^2 + 5x + 6 = 0"  # 相似题目
    question3 = "计算圆的面积"  # 不相关题目
    
    emb1 = get_question_embedding(question1)
    emb2 = get_question_embedding(question2)
    emb3 = get_question_embedding(question3)
    
    if emb1 and emb2 and emb3:
        sim12 = cosine_similarity(emb1, emb2)
        sim13 = cosine_similarity(emb1, emb3)
        print(f"✓ 相似题目相似度: {sim12:.4f}")
        print(f"✓ 不相关题目相似度: {sim13:.4f}")
        if sim12 > sim13:
            print("✓ 相似度计算正确（相似题目 > 不相关题目）")
        else:
            print("⚠ 相似度计算可能有问题（相似题目 <= 不相关题目）")
    else:
        print("✗ 获取 embedding 失败，无法测试相似度")
        sys.exit(1)
    
    # 测试 3: 查找相似题目
    print("\n[测试 3] 查找相似题目")
    current_q = "求解方程 x^2 + 5x + 6 = 0"
    other_questions = [
        ("task1", "解方程 x^2 + 5x + 6 = 0"),  # 非常相似
        ("task2", "求解二次方程 x^2 + 5x + 6 = 0"),  # 相似
        ("task3", "计算圆的面积公式"),  # 不相关
        ("task4", "求解不等式 x + 3 > 5"),  # 部分相关
        ("task5", "因式分解 x^2 + 5x + 6"),  # 相关
        ("task6", "计算三角形的面积"),  # 不相关
        ("task7", "求解方程 2x^2 + 10x + 12 = 0"),  # 相似（倍数关系）
        ("task8", "求函数 f(x) = x^2 的导数"),  # 部分相关
        ("task9", "求解方程 x^2 - 4 = 0"),  # 相关（同类方程）
        ("task10", "计算 1 + 1 = ?"),  # 不相关
    ]
    
    similar_results = find_similar_questions(current_q, other_questions, top_k=5)
    
    if similar_results:
        print(f"✓ 成功找到 {len(similar_results)} 个相似题目:")
        for i, (task_id, similarity) in enumerate(similar_results, 1):
            # 找到对应的题目文本
            q_text = next((q[1] for q in other_questions if q[0] == task_id), "未知")
            print(f"  {i}. [{task_id}] 相似度: {similarity:.4f}")
            print(f"     题目: {q_text[:50]}...")
        
        # 验证：最相似的应该是 task1 或 task2
        top_task = similar_results[0][0]
        if top_task in ["task1", "task2"]:
            print("✓ 最相似的题目符合预期")
        else:
            print(f"⚠ 最相似的题目是 {top_task}，可能不符合预期")
    else:
        print("✗ 查找相似题目失败")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)
