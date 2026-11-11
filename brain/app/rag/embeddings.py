import logging
import hashlib
from typing import List, Optional
import numpy as np
from app.config import settings
from app.rag.text import tokenize

log = logging.getLogger("brain.embeddings")

LOCAL_DIM = 384
FASTEMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
FASTEMBED_BACKEND = f"fastembed:{FASTEMBED_MODEL_NAME}"
HASH_BACKEND = f"local-hash-v2-{LOCAL_DIM}"
LOCAL_BACKEND = FASTEMBED_BACKEND


class EmbeddingService:
    """
    Embeds text with either FastEmbed (state-of-the-art offline ONNX transformer),
    an API model (via OpenAI / proxy), or a deterministic hash fallback.

    The backends produce vectors in different spaces, so an index must always
    be queried with the backend that built it. The backend name is recorded
    in the index manifest (index_info.json) and passed back in here.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._api_unavailable = False
        self._fastembed_model = None
        self._fastembed_unavailable = False

    @property
    def api_backend(self) -> str:
        return f"api:{self.model_name}"

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm == 0:
            return vec
        return vec / norm

    def api_available(self) -> bool:
        return bool(settings.OPENAI_API_KEY or settings.CODECRAFT_KEY) and not self._api_unavailable

    def _get_fastembed(self):
        if self._fastembed_model is None and not self._fastembed_unavailable:
            try:
                from fastembed import TextEmbedding
                self._fastembed_model = TextEmbedding(model_name=FASTEMBED_MODEL_NAME)
                log.info("Initialized high-performance FastEmbed model: %s", FASTEMBED_MODEL_NAME)
            except Exception as e:
                log.warning("FastEmbed unavailable (%s). Falling back to hash embedder.", e)
                self._fastembed_unavailable = True
        return self._fastembed_model

    def _fastembed_embed(self, text: str) -> List[float]:
        model = self._get_fastembed()
        if model is None:
            return self._local_fallback_embed(text)
        vec = list(model.embed([text]))[0]
        return self._normalize(np.array(vec, dtype=np.float32)).tolist()

    def resolve_backend(self, prefer_local: bool = False) -> str:
        """
        Picks the backend for a new build: probes API if preferred, otherwise uses FastEmbed.
        """
        if prefer_local:
            return FASTEMBED_BACKEND if not self._fastembed_unavailable else HASH_BACKEND

        if self.api_available():
            try:
                self._embed_api("probe")
                return self.api_backend
            except Exception as e:
                log.info("API embedding unavailable (%s). Using FastEmbed for this build.", e)
                self._api_unavailable = True

        return FASTEMBED_BACKEND if not self._fastembed_unavailable else HASH_BACKEND

    def _embed_api(self, text: str) -> List[float]:
        from app.llm.client import llm_client
        vec = llm_client.embed(text, model=self.model_name)
        return self._normalize(np.array(vec, dtype=np.float32)).tolist()

    def embed_with_backend(self, text: str, backend: str) -> List[float]:
        """
        Embeds with an explicit backend. Raises if the API backend fails, so callers
        never silently mix vector spaces.
        """
        clean_text = text.strip()
        if not clean_text:
            return [0.0] * LOCAL_DIM

        if backend == FASTEMBED_BACKEND or backend.startswith("fastembed:"):
            return self._fastembed_embed(clean_text)
        if backend == HASH_BACKEND or backend.startswith("local-hash"):
            return self._local_fallback_embed(clean_text)
        if backend.startswith("api:"):
            return self._embed_api(clean_text)

        # Default to FastEmbed
        return self._fastembed_embed(clean_text)

    def embed_text(self, text: str) -> List[float]:
        """
        Embeds a single string into a normalized dense vector.
        Uses FastEmbed / API if available and reachable; falls back cleanly to hash.
        """
        clean_text = text.strip()
        if not clean_text:
            return [0.0] * LOCAL_DIM

        # Try API embeddings if key is present and API was not previously marked unavailable
        if self.api_available():
            try:
                return self._embed_api(clean_text)
            except Exception as e:
                log.info("API embedding unavailable (%s). Switching to FastEmbed.", e)
                self._api_unavailable = True

        return self._fastembed_embed(clean_text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]

    def _local_fallback_embed(self, text: str, dim: int = LOCAL_DIM) -> List[float]:
        """
        Deterministic, fast multilingual representation for offline / sandbox mode.
        Projects character n-grams and word tokens into a fixed-dimension vector space.
        Stopwords are dropped and plurals stemmed, so "what/the/does" cannot make
        unrelated texts look similar.
        """
        words = tokenize(text)
        vec = np.zeros(dim, dtype=np.float32)

        for word in words:
            # Word level hash
            h1 = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx1 = h1 % dim
            sign1 = 1.0 if (h1 >> 8) % 2 == 0 else -1.0
            vec[idx1] += sign1 * 1.5

            # Sub-word char n-grams for multilingual (Sinhala/Tamil/English)
            for n in range(3, min(6, len(word) + 1)):
                ngram = word[:n]
                h2 = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest(), 16)
                idx2 = h2 % dim
                sign2 = 1.0 if (h2 >> 4) % 2 == 0 else -1.0
                vec[idx2] += sign2 * 0.8

        return self._normalize(vec).tolist()


embedding_service = EmbeddingService()
