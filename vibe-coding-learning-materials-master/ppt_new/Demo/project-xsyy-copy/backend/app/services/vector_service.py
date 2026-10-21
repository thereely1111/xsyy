from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class VectorService:
    _instance: Optional["VectorService"] = None
    _embedding_model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._embedding_model is None:
            self._initialize_model()

    def _initialize_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            from app.config import settings
            self._embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.warning(f"Could not load embedding model: {e}")
            self._embedding_model = None

    async def get_embedding(self, text: str) -> List[float]:
        if self._embedding_model is None:
            logger.warning("Embedding model not available, using random embedding")
            import random
            return [random.random() for _ in range(384)]

        try:
            embedding = self._embedding_model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            import random
            return [random.random() for _ in range(384)]

    def search_similar(self, query_embedding: List[float], limit: int = 5) -> dict:
        from app.vector_db import get_vector_db

        try:
            vector_db = get_vector_db()
            results = vector_db.search_similar(query_embedding, limit)
            return results
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return {"ids": [[]], "distances": [[]], "documents": [[]]}

    def add_vector(self, work_id: int, text: str, embedding: List[float]):
        from app.vector_db import get_vector_db

        try:
            vector_db = get_vector_db()
            vector_db.add_vector(work_id, text, embedding)
            logger.info(f"Vector added for work_id: {work_id}")
        except Exception as e:
            logger.error(f"Failed to add vector: {e}")

    def delete_vector(self, work_id: int):
        from app.vector_db import get_vector_db

        try:
            vector_db = get_vector_db()
            vector_db.delete_vector(work_id)
            logger.info(f"Vector deleted for work_id: {work_id}")
        except Exception as e:
            logger.error(f"Failed to delete vector: {e}")


_vector_service: Optional[VectorService] = None


def get_vector_service() -> VectorService:
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorService()
    return _vector_service
