import logging
import hashlib
from typing import List, Optional
import numpy as np
from app.config import settings

log = logging.getLogger("brain.embeddings")


class EmbeddingService:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._api_unavailable = False

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm == 0:
            return vec
        return vec / norm

    def embed_text(self, text: str) -> List[float]:
        """
        Embeds a single string into a normalized dense vector.
        Uses API if available and reachable; falls back cleanly to local embedding.
        """
        clean_text = text.strip()
        if not clean_text:
            return [0.0] * 384

        # Try API embeddings if key is present and API was not previously marked unavailable
        if not self._api_unavailable and (settings.OPENAI_API_KEY):
            try:
                from app.llm.client import llm_client
                vec = llm_client.embed(clean_text)
                return self._normalize(np.array(vec, dtype=np.float32)).tolist()
            except Exception as e:
                log.info("API embedding unavailable (%s). Switching to fast local embeddings.", e)
                self._api_unavailable = True

        return self._local_fallback_embed(clean_text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]

    def _local_fallback_embed(self, text: str, dim: int = 384) -> List[float]:
        """
        Deterministic, fast multilingual representation for offline / sandbox mode.
        Projects character n-grams and word tokens into a fixed-dimension vector space.
        """
        words = text.lower().split()
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
