import hashlib

import numpy as np
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from config import EVENT_ALPHA, QDRANT_COLLECTION, QDRANT_URL, VECTOR_DIM

client = AsyncQdrantClient(url=QDRANT_URL)


async def init_qdrant():
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if QDRANT_COLLECTION not in names:
        await client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


def embed_text_fast(text: str, dim: int = VECTOR_DIM):
    """
    最简单的稳定向量方案：
    用哈希生成伪随机向量。
    这是 Demo 用，后续可以替换成真实 embedding。
    """
    if not text:
        text = "empty"

    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], "little", signed=False)
    rng = np.random.default_rng(seed)
    v = rng.normal(0, 1, size=(dim,)).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v.tolist()


def build_item_text(title: str, description: str, modality: str, tags=None):
    tags = tags or []
    return f"[{modality}] {title} {description} {' '.join(tags)}"


async def upsert_item_to_qdrant(item):
    item_text = build_item_text(
        item["title"],
        item["description"],
        item["modality"],
        item.get("tags", []),
    )
    vector = embed_text_fast(item_text)

    point = PointStruct(
        id=item["item_id"],
        vector=vector,
        payload={
            "title": item["title"],
            "description": item["description"],
            "modality": item["modality"],
            "author_id": item.get("author_id", ""),
            "tags": item.get("tags", []),
            "created_at": item.get("created_at", ""),
        },
    )
    await client.upsert(collection_name=QDRANT_COLLECTION, points=[point])


async def get_item_vector(item_id: int):
    records = await client.retrieve(
        collection_name=QDRANT_COLLECTION,
        ids=[item_id],
        with_vectors=True,
        with_payload=False,
    )
    if not records:
        return None
    return records[0].vector


def normalize(v):
    arr = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm < 1e-12:
        return arr.tolist()
    return (arr / norm).tolist()


def update_profile_vector(old_vec, item_vec, event_type: str):
    alpha = EVENT_ALPHA.get(event_type, 0.08)
    old_arr = np.array(old_vec, dtype=np.float32)
    item_arr = np.array(item_vec, dtype=np.float32)
    new_arr = (1 - alpha) * old_arr + alpha * item_arr
    return normalize(new_arr)


async def search_similar_items(user_vec, limit=20):
    res = await client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=user_vec,
        limit=limit,
        with_payload=True,
    )
    return res.points
