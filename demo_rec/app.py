from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import DEFAULT_K
from db import (
    create_user,
    get_latest_items,
    get_user_vector,
    init_db,
    insert_event,
    insert_item,
    update_user_vector,
)
from recommender import (
    get_item_vector,
    init_qdrant,
    search_similar_items,
    update_profile_vector,
    upsert_item_to_qdrant,
)

app = FastAPI(title="Demo Recommendation System")


class UserInitRequest(BaseModel):
    users: List[str]


class ItemData(BaseModel):
    item_id: int
    title: str
    description: str
    modality: str
    author_id: Optional[str] = ""
    tags: Optional[List[str]] = []
    image_url: Optional[str] = ""
    created_at: Optional[str] = ""


class ItemInitRequest(BaseModel):
    items: List[ItemData]


class CreateUserRequest(BaseModel):
    user_id: str


class EventRequest(BaseModel):
    user_id: str
    recent_item_ids: List[int] = []
    recent_events: List[str] = []
    k: Optional[int] = DEFAULT_K


@app.on_event("startup")
async def startup():
    await init_db()
    await init_qdrant()


@app.post("/init/users")
async def init_users(req: UserInitRequest):
    for user_id in req.users:
        await create_user(user_id)
    return {"message": "users initialized", "count": len(req.users)}


@app.post("/init/items")
async def init_items(req: ItemInitRequest):
    count = 0
    for item in req.items:
        item_dict = item.dict()
        await insert_item(item_dict)
        await upsert_item_to_qdrant(item_dict)
        count += 1
    return {"message": "items initialized", "count": count}


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
