import os

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "qdrant_data")
QDRANT_COLLECTION = "items_demo"

SQLITE_PATH = "demo_rec.sqlite"

# Small text-only embedding model for faster item vectorization.
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# all-MiniLM-L6-v2 output vector dim
VECTOR_DIM = 384

# event weights
EVENT_ALPHA = {
    "view": 0.08,
    "like": 0.15,
    "favorite": 0.25,
}

# cold start default result count
DEFAULT_K = 20
