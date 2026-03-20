from typing import Optional

import numpy as np
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from config import (
    EMBEDDING_MODEL_NAME,
    EVENT_ALPHA,
    QDRANT_COLLECTION,
    QDRANT_LOCAL_PATH,
    QDRANT_URL,
    VECTOR_DIM,
)

_client_config = {"url": QDRANT_URL} if QDRANT_URL else {"path": QDRANT_LOCAL_PATH}
client = AsyncQdrantClient(**_client_config)
_model: Optional[SentenceTransformer] = None


def get_text_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


async def init_qdrant():
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if QDRANT_COLLECTION not in names:
        await client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        return

    collection_info = await client.get_collection(collection_name=QDRANT_COLLECTION)
    existing_size = collection_info.config.params.vectors.size
    if existing_size != VECTOR_DIM:
        await client.delete_collection(collection_name=QDRANT_COLLECTION)
        await client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


def normalize(v):
    arr = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm < 1e-12:
        return arr.tolist()
    return (arr / norm).tolist()


def build_item_text(title: str, description: str, modality: str, tags=None):
    tags = tags or []
    return f"[{modality}] {title} {description} {' '.join(tags)}"


def embed_text(text: str):
    model = get_text_embedding_model()
    emb = model.encode(text or "empty", normalize_embeddings=True)
    return emb.astype(np.float32).tolist()


async def upsert_item_to_qdrant(item):
    item_text = build_item_text(
        item["title"],
        item["description"],
        item["modality"],
        item.get("tags", []),
    )
    vector = embed_text(item_text)

    point = PointStruct(
        id=item["item_id"],
        vector=vector,
        payload={
            "title": item["title"],
            "description": item["description"],
            "modality": item["modality"],
            "author_id": item.get("author_id", ""),
            "tags": item.get("tags", []),
            "image_url": item.get("image_url", ""),
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


async def qdrant_healthcheck():
    try:
        await client.get_collections()
        return {"ok": True, "error": ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def list_qdrant_collections():
    data = await client.get_collections()
    return [c.name for c in data.collections]


async def get_qdrant_collection(collection_name: str):
    info = await client.get_collection(collection_name=collection_name)
    return info


async def scroll_qdrant_points(
    collection_name: str,
    limit: int = 10,
    with_payload: bool = True,
    with_vectors: bool = False,
):
    points, next_page_offset = await client.scroll(
        collection_name=collection_name,
        limit=limit,
        with_payload=with_payload,
        with_vectors=with_vectors,
    )
    return points, next_page_offset
