import os

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "qdrant_data")
QDRANT_COLLECTION = "items_demo"

SQLITE_PATH = "demo_rec.sqlite"

# CLIP ViT-B/32 output vector dim
VECTOR_DIM = 512

# event weights
EVENT_ALPHA = {
    "view": 0.08,
    "like": 0.15,
    "favorite": 0.25,
}

# cold start default result count
DEFAULT_K = 20

# multimodal embedding model (text + image)
MULTIMODAL_MODEL_NAME = "sentence-transformers/clip-ViT-B-32"
