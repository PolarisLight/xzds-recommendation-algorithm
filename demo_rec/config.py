QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "items_demo"

SQLITE_PATH = "demo_rec.sqlite"

VECTOR_DIM = 384

# 行为权重
EVENT_ALPHA = {
    "view": 0.08,
    "like": 0.15,
    "favorite": 0.25,
}

# 冷启动默认返回数量
DEFAULT_K = 20
