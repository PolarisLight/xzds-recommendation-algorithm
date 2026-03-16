from io import BytesIO
from typing import Optional

import numpy as np
import requests
from PIL import Image
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from config import (
    EVENT_ALPHA,
    MULTIMODAL_MODEL_NAME,
    QDRANT_COLLECTION,
    QDRANT_URL,
    VECTOR_DIM,
)

client = AsyncQdrantClient(url=QDRANT_URL)
_model: Optional[SentenceTransformer] = None


def get_multimodal_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MULTIMODAL_MODEL_NAME)
    return _model


async def init_qdrant():
    collections = await client.get_collections()
    names = [c.name for c in collections.collections]
    if QDRANT_COLLECTION not in names:
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


def embed_text_real(text: str):
    model = get_multimodal_model()
    emb = model.encode(text or "empty", normalize_embeddings=True)
    return emb.astype(np.float32).tolist()


def embed_image_real(image_url: str):
    model = get_multimodal_model()
    resp = requests.get(image_url, timeout=10)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    emb = model.encode(img, normalize_embeddings=True)
    return emb.astype(np.float32).tolist()


def fuse_multimodal_embedding(text_vector, image_vector=None, text_weight=0.7, image_weight=0.3):
    if image_vector is None:
        return normalize(text_vector)

    text_arr = np.array(text_vector, dtype=np.float32)
    image_arr = np.array(image_vector, dtype=np.float32)
    fused = text_weight * text_arr + image_weight * image_arr
    return normalize(fused)


async def upsert_item_to_qdrant(item):
    item_text = build_item_text(
        item["title"],
        item["description"],
        item["modality"],
        item.get("tags", []),
    )

    text_vector = embed_text_real(item_text)
    image_url = item.get("image_url") or ""
    image_vector = None

    if image_url:
        try:
            image_vector = embed_image_real(image_url)
        except Exception:
            # 图片失败时仅使用文本向量，保证主流程可用
            image_vector = None

    vector = fuse_multimodal_embedding(text_vector, image_vector)

    point = PointStruct(
        id=item["item_id"],
        vector=vector,
        payload={
            "title": item["title"],
            "description": item["description"],
            "modality": item["modality"],
            "author_id": item.get("author_id", ""),
            "tags": item.get("tags", []),
            "image_url": image_url,
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
