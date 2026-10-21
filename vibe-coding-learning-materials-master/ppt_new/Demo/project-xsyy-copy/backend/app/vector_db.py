import chromadb
from chromadb.config import Settings
from app.config import settings
from typing import Optional, List


class VectorDB:
    _instance: Optional["VectorDB"] = None
    _client: Optional[chromadb.Client] = None
    _collection = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._client = chromadb.Client(Settings(
                persist_directory=settings.CHROMA_PATH,
                anonymized_telemetry=False
            ))
            self._collection = self._client.get_or_create_collection(
                name="math_questions",
                metadata={"hnsw:space": "cosine"}
            )

    def add_vector(self, work_id: int, text: str, embedding: List[float]):
        self._collection.add(
            ids=[str(work_id)],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"work_id": work_id}]
        )

    def search_similar(self, query_embedding: List[float], limit: int = 5) -> dict:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )
        return results

    def delete_vector(self, work_id: int):
        self._collection.delete(ids=[str(work_id)])

    def get_collection_info(self) -> dict:
        return {
            "name": self._collection.name,
            "count": self._collection.count()
        }


vector_db = VectorDB()


def get_vector_db() -> VectorDB:
    return vector_db
