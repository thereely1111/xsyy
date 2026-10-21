import chromadb
from chromadb.config import Settings
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHROMA_PATH = os.environ.get("CHROMA_PATH", "./chroma_data")

def init_vector_db():
    os.makedirs(CHROMA_PATH, exist_ok=True)

    client = chromadb.Client(Settings(
        persist_directory=CHROMA_PATH,
        anonymized_telemetry=False
    ))

    collection = client.get_or_create_collection(
        name="math_questions",
        metadata={"hnsw:space": "cosine", "description": "Math problem embeddings for XSYY"}
    )

    logger.info(f"Vector DB initialized at: {CHROMA_PATH}")
    logger.info(f"Collection '{collection.name}' created/loaded")
    logger.info(f"Current collection count: {collection.count()}")

    try:
        collection.add(
            ids=["demo_1"],
            embeddings=[[0.0] * 384],
            documents=["这是一个测试向量用于初始化ChromaDB"],
            metadatas=[{"work_id": 0, "type": "demo"}]
        )
        logger.info("Demo vector added successfully")
    except Exception as e:
        logger.warning(f"Could not add demo vector: {e}")

    return client, collection

def get_collection_info():
    client = chromadb.Client(Settings(
        persist_directory=CHROMA_PATH,
        anonymized_telemetry=False
    ))

    collection = client.get_or_create_collection(
        name="math_questions",
        metadata={"hnsw:space": "cosine"}
    )

    return {
        "name": collection.name,
        "count": collection.count(),
        "metadata": collection.metadata
    }

if __name__ == "__main__":
    print("=" * 50)
    print("象数演易 - ChromaDB 向量数据库初始化")
    print("=" * 50)

    client, collection = init_vector_db()

    info = get_collection_info()
    print(f"\nCollection Name: {info['name']}")
    print(f"Vector Count: {info['count']}")
    print(f"Distance Metric: {info['metadata'].get('hnsw:space', 'cosine')}")

    print("\n初始化完成!")
