QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "items_demo"

SQLITE_PATH = "demo_rec.sqlite"

# CLIP ViT-B/32 输出 512 维向量
VECTOR_DIM = 512

# 行为权重
EVENT_ALPHA = {
    "view": 0.08,
    "like": 0.15,
    "favorite": 0.25,
}

# 冷启动默认返回数量
DEFAULT_K = 20

# 真实多模态 embedding 模型（文本 + 图片）
MULTIMODAL_MODEL_NAME = "sentence-transformers/clip-ViT-B-32"
