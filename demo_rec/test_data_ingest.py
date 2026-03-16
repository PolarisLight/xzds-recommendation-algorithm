import json
import sqlite3

SQLITE_PATH = "demo_rec.sqlite"
VECTOR_DIM = 512

TEST_USER = {"user_id": "test_user_001"}
TEST_ITEM = {
    "item_id": 10001,
    "title": "测试推文：春天来了",
    "description": "这是一条用于验证入库功能的测试推文（包含图片）",
    "modality": "image_text",
    "author_id": "author_test_01",
    "tags": ["测试", "推文", "入库", "多模态"],
    "image_url": "https://images.unsplash.com/photo-1503023345310-bd7c1de61c7d",
    "created_at": "2026-03-15 12:00:00",
}

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
"""


def main():
    conn = sqlite3.connect(SQLITE_PATH)
    try:
        conn.executescript(CREATE_TABLES_SQL)

        zero_vec = json.dumps([0.0] * VECTOR_DIM)
        conn.execute(
            "INSERT OR REPLACE INTO users(user_id, profile_vector) VALUES(?, ?)",
            (TEST_USER["user_id"], zero_vec),
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO items(item_id, title, description, modality, author_id, tags, image_url, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TEST_ITEM["item_id"],
                TEST_ITEM["title"],
                TEST_ITEM["description"],
                TEST_ITEM["modality"],
                TEST_ITEM["author_id"],
                json.dumps(TEST_ITEM["tags"], ensure_ascii=False),
                TEST_ITEM["image_url"],
                TEST_ITEM["created_at"],
            ),
        )
        conn.commit()

        user_row = conn.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (TEST_USER["user_id"],),
        ).fetchone()
        item_row = conn.execute(
            "SELECT item_id, title, modality, author_id, tags, image_url FROM items WHERE item_id=?",
            (TEST_ITEM["item_id"],),
        ).fetchone()

        assert user_row is not None, "用户入库失败：未找到测试用户"
        assert item_row is not None, "推文入库失败：未找到测试推文"

        print("[PASS] 用户入库成功:", {"user_id": user_row[0]})
        print(
            "[PASS] 推文入库成功:",
            {
                "item_id": item_row[0],
                "title": item_row[1],
                "modality": item_row[2],
                "author_id": item_row[3],
                "tags": json.loads(item_row[4]) if item_row[4] else [],
                "image_url": item_row[5] or "",
            },
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
