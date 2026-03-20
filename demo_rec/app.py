from collections import defaultdict
from typing import Any, List

import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

if __package__ in (None, ""):
    from config import DEFAULT_K, SQLITE_PATH, VECTOR_UPSERT_BATCH_SIZE
    from db import (
        create_user,
        get_latest_items,
        get_user_vector,
        init_db,
        insert_event,
        insert_item,
        insert_items,
        update_user_vector,
    )
    from recommender import (
        get_item_vector,
        get_qdrant_collection,
        init_qdrant,
        list_qdrant_collections,
        qdrant_healthcheck,
        scroll_qdrant_points,
        search_similar_items,
        update_profile_vector,
        upsert_item_to_qdrant,
        upsert_items_to_qdrant,
    )
else:
    from .config import DEFAULT_K, SQLITE_PATH, VECTOR_UPSERT_BATCH_SIZE
    from .db import (
        create_user,
        get_latest_items,
        get_user_vector,
        init_db,
        insert_event,
        insert_item,
        insert_items,
        update_user_vector,
    )
    from .recommender import (
        get_item_vector,
        get_qdrant_collection,
        init_qdrant,
        list_qdrant_collections,
        qdrant_healthcheck,
        scroll_qdrant_points,
        search_similar_items,
        update_profile_vector,
        upsert_item_to_qdrant,
        upsert_items_to_qdrant,
    )

app = FastAPI(title="Demo Recommendation System")
_user_refresh_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class UserInitRequest(BaseModel):
    users: List[str]


class ItemData(BaseModel):
    item_id: int
    title: str
    description: str
    modality: str
    author_id: str = ""
    tags: List[str] = Field(default_factory=list)
    image_url: str = ""
    created_at: str = ""


class ItemInitRequest(BaseModel):
    items: List[ItemData]
    vector_batch_size: int = Field(default=VECTOR_UPSERT_BATCH_SIZE, ge=1, le=1000)


class CreateUserRequest(BaseModel):
    user_id: str


class EventRequest(BaseModel):
    user_id: str
    recent_item_ids: List[int] = Field(default_factory=list)
    recent_events: List[str] = Field(default_factory=list)
    k: int = DEFAULT_K


class QdrantScrollRequest(BaseModel):
    limit: int = 10
    with_payload: bool = True
    with_vector: bool = False


@app.on_event("startup")
async def startup():
    print("APP SQLITE_PATH =", SQLITE_PATH)
    await init_db()
    await init_qdrant()


@app.post("/init/users")
async def init_users(req: UserInitRequest):
    for user_id in req.users:
        await create_user(user_id)
    return {"message": "users initialized", "count": len(req.users)}


@app.post("/init/items")
async def init_items(req: ItemInitRequest):
    item_dicts = [item.dict() for item in req.items]
    await insert_items(item_dicts)
    await upsert_items_to_qdrant(item_dicts, batch_size=req.vector_batch_size)
    return {
        "message": "items initialized",
        "count": len(item_dicts),
        "vector_batch_size": req.vector_batch_size,
    }


@app.post("/users")
async def create_new_user(req: CreateUserRequest):
    await create_user(req.user_id)
    return {"message": "user created", "user_id": req.user_id}


@app.post("/items")
async def create_item(item: ItemData):
    item_dict = item.dict()
    await insert_item(item_dict)
    await upsert_item_to_qdrant(item_dict)
    return {"message": "item created", "item_id": item.item_id}


@app.post("/feed/refresh")
async def refresh_feed(req: EventRequest):
    async with _user_refresh_locks[req.user_id]:
        user_vec = await get_user_vector(req.user_id)
        if user_vec is None:
            raise HTTPException(status_code=404, detail="user not found")

        if len(req.recent_item_ids) != len(req.recent_events):
            raise HTTPException(
                status_code=400,
                detail="recent_item_ids and recent_events length mismatch",
            )

        updated_vec = user_vec
        for item_id, event_type in zip(req.recent_item_ids, req.recent_events):
            item_vec = await get_item_vector(item_id)
            if item_vec is not None:
                updated_vec = update_profile_vector(updated_vec, item_vec, event_type)
                await insert_event(req.user_id, item_id, event_type)

        await update_user_vector(req.user_id, updated_vec)

    if sum(abs(x) for x in updated_vec) < 1e-8:
        latest_items = await get_latest_items(limit=req.k or DEFAULT_K)
        return {
            "user_id": req.user_id,
            "mode": "cold_start_latest",
            "items": latest_items,
        }

    points = await search_similar_items(updated_vec, limit=req.k or DEFAULT_K)

    items = []
    for p in points:
        items.append(
            {
                "item_id": p.id,
                "score": p.score,
                "title": p.payload.get("title", ""),
                "description": p.payload.get("description", ""),
                "modality": p.payload.get("modality", ""),
                "author_id": p.payload.get("author_id", ""),
                "tags": p.payload.get("tags", []),
                "image_url": p.payload.get("image_url", ""),
                "created_at": p.payload.get("created_at", ""),
            }
        )

    return {"user_id": req.user_id, "mode": "personalized", "items": items}


@app.get("/readyz")
async def readyz():
    qdrant = await qdrant_healthcheck()
    return {"status": "ok" if qdrant["ok"] else "degraded", "qdrant": qdrant}


@app.get("/qdrant/collections")
async def qdrant_collections():
    names = await list_qdrant_collections()
    return {"collections": names}


@app.get("/qdrant/collections/{collection_name}")
async def qdrant_collection_detail(collection_name: str):
    info = await get_qdrant_collection(collection_name)
    return info.model_dump() if hasattr(info, "model_dump") else info.dict()


@app.post("/qdrant/collections/{collection_name}/points/scroll")
async def qdrant_scroll(collection_name: str, req: QdrantScrollRequest):
    points, next_page_offset = await scroll_qdrant_points(
        collection_name=collection_name,
        limit=req.limit,
        with_payload=req.with_payload,
        with_vectors=req.with_vector,
    )

    def point_to_dict(p: Any):
        return {
            "id": p.id,
            "payload": p.payload,
            "vector": p.vector if req.with_vector else None,
        }

    return {
        "points": [point_to_dict(p) for p in points],
        "next_page_offset": next_page_offset,
    }
