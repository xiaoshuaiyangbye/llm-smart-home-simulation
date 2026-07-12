from pathlib import Path
import os
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Unit tests must not depend on a locally running embedding service. Production
# and local development can still opt into RAG_RETRIEVAL_MODE=local_embedding.
os.environ["RAG_RETRIEVAL_MODE"] = "lexical"
