import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", str(BASE_DIR / "qdrant_data"))
QDRANT_COLLECTION = "items_demo"

SQLITE_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "demo_rec.sqlite"))


def _resolve_embedding_model_name() -> str:
    configured = os.getenv("EMBEDDING_MODEL_NAME", "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.exists():
            return str(configured_path.resolve())
        return configured

    bundled_model_dir = BASE_DIR / "all-MiniLM-L6-v2"
    if bundled_model_dir.exists():
        return str(bundled_model_dir)

    return "sentence-transformers/all-MiniLM-L6-v2"


EMBEDDING_MODEL_NAME = _resolve_embedding_model_name()
EMBEDDING_LOCAL_FILES_ONLY = os.getenv("EMBEDDING_LOCAL_FILES_ONLY", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
if Path(EMBEDDING_MODEL_NAME).exists():
    EMBEDDING_LOCAL_FILES_ONLY = True

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

# 向量化/入库批次大小
VECTOR_UPSERT_BATCH_SIZE = int(os.getenv("VECTOR_UPSERT_BATCH_SIZE", "64"))
