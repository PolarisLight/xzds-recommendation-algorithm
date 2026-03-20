import asyncio
import json
import sqlite3

import aiosqlite

if __package__ in (None, ""):
    from config import SQLITE_PATH, VECTOR_DIM
else:
    from .config import SQLITE_PATH, VECTOR_DIM

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    profile_vector TEXT
);

CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    title TEXT,
    description TEXT,
    modality TEXT,
    author_id TEXT,
    tags TEXT,
    image_url TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    item_id INTEGER,
    event_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

DB_BUSY_TIMEOUT_MS = 30_000
DB_LOCK_RETRY_COUNT = 5
DB_LOCK_RETRY_DELAY_SEC = 0.05


async def _connect():
    db = await aiosqlite.connect(SQLITE_PATH, timeout=DB_BUSY_TIMEOUT_MS / 1000)
    await db.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA synchronous = NORMAL")
    return db


async def _close_db(db):
    await db.close()


async def _run_with_db_retry(operation):
    for attempt in range(DB_LOCK_RETRY_COUNT):
        try:
            return await operation()
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower() or attempt == DB_LOCK_RETRY_COUNT - 1:
                raise
            await asyncio.sleep(DB_LOCK_RETRY_DELAY_SEC * (attempt + 1))


async def _ensure_items_column(db, column_name: str, ddl: str):
    cur = await db.execute("PRAGMA table_info(items)")
    columns = await cur.fetchall()
    names = {c[1] for c in columns}
    if column_name not in names:
        await db.execute(ddl)


async def _reset_mismatched_user_vectors(db):
    cur = await db.execute("SELECT user_id, profile_vector FROM users")
    rows = await cur.fetchall()
    for user_id, profile_vector in rows:
        try:
            vector = json.loads(profile_vector) if profile_vector else []
        except json.JSONDecodeError:
            vector = []
        if len(vector) != VECTOR_DIM:
            zero_vec = json.dumps([0.0] * VECTOR_DIM)
            await db.execute(
                "UPDATE users SET profile_vector=? WHERE user_id=?",
                (zero_vec, user_id),
            )


async def init_db():
    async def operation():
        db = await _connect()
        try:
            await db.executescript(CREATE_TABLES_SQL)
            await _ensure_items_column(db, "image_url", "ALTER TABLE items ADD COLUMN image_url TEXT")
            await _reset_mismatched_user_vectors(db)
            await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def create_user(user_id: str):
    async def operation():
        db = await _connect()
        try:
            cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            if row is None:
                zero_vec = json.dumps([0.0] * VECTOR_DIM)
                await db.execute(
                    "INSERT INTO users(user_id, profile_vector) VALUES(?, ?)",
                    (user_id, zero_vec),
                )
                await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def get_user_vector(user_id: str):
    db = await _connect()
    try:
        cur = await db.execute("SELECT profile_vector FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        vector = json.loads(row[0])
        if len(vector) != VECTOR_DIM:
            return [0.0] * VECTOR_DIM
        return vector
    finally:
        await _close_db(db)


async def update_user_vector(user_id: str, vector):
    async def operation():
        db = await _connect()
        try:
            await db.execute(
                "UPDATE users SET profile_vector=? WHERE user_id=?",
                (json.dumps(vector), user_id),
            )
            await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def persist_user_feedback(user_id: str, item_events, profile_vector):
    async def operation():
        db = await _connect()
        try:
            if item_events:
                await db.executemany(
                    "INSERT INTO user_events(user_id, item_id, event_type) VALUES(?, ?, ?)",
                    [(user_id, item_id, event_type) for item_id, event_type in item_events],
                )
            await db.execute(
                "UPDATE users SET profile_vector=? WHERE user_id=?",
                (json.dumps(profile_vector), user_id),
            )
            await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def insert_item(item):
    async def operation():
        db = await _connect()
        try:
            await db.execute(
                """
                INSERT OR REPLACE INTO items(
                    item_id, title, description, modality, author_id, tags, image_url, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["item_id"],
                    item["title"],
                    item["description"],
                    item["modality"],
                    item.get("author_id", ""),
                    json.dumps(item.get("tags", []), ensure_ascii=False),
                    item.get("image_url", ""),
                    item.get("created_at", ""),
                ),
            )
            await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def insert_event(user_id: str, item_id: int, event_type: str):
    async def operation():
        db = await _connect()
        try:
            await db.execute(
                "INSERT INTO user_events(user_id, item_id, event_type) VALUES(?, ?, ?)",
                (user_id, item_id, event_type),
            )
            await db.commit()
        finally:
            await _close_db(db)

    await _run_with_db_retry(operation)


async def get_latest_items(limit=20):
    db = await _connect()
    try:
        cur = await db.execute(
            """
            SELECT item_id, title, description, modality, author_id, tags, image_url, created_at
            FROM items
            ORDER BY created_at DESC, item_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    finally:
        await _close_db(db)

    result = []
    for r in rows:
        result.append(
            {
                "item_id": r[0],
                "title": r[1],
                "description": r[2],
                "modality": r[3],
                "author_id": r[4],
                "tags": json.loads(r[5]) if r[5] else [],
                "image_url": r[6] or "",
                "created_at": r[7],
            }
        )
    return result
