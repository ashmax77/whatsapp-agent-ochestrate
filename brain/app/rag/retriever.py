import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel
from app.config import settings
from app.rag.embeddings import embedding_service

log = logging.getLogger("brain.retriever")
INDEX_FILE = settings.CHROMA_PATH / "kb_customer.json"


class Hit(BaseModel):
    id: str
    text: str
    meta: Dict[str, Any]
    distance: float  # Cosine distance: 0.0 (identical) to 2.0 (opposite)


class KnowledgeRetriever:
    def __init__(self, index_file: Optional[Path] = None):
        self.index_file = index_file or INDEX_FILE
        self._documents: List[Dict[str, Any]] = []
        self._matrix: Optional[np.ndarray] = None
        self.load_index()

    def load_index(self):
        if not self.index_file.exists():
            log.warning("Vector index not found at %s. Running with empty index.", self.index_file)
            self._documents = []
            self._matrix = None
            return

        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                self._documents = json.load(f)

            if self._documents:
                vectors = [doc["vector"] for doc in self._documents]
                self._matrix = np.array(vectors, dtype=np.float32)
                log.info("Loaded %d documents from index %s", len(self._documents), self.index_file)
        except Exception as e:
            log.error("Failed to load knowledge index: %s", e)
            self._documents = []
            self._matrix = None

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        branch_id: Optional[str] = None
    ) -> List[Hit]:
        """
        Retrieves top-k relevant knowledge chunks for a query.
        MANDATORY SECURITY RULE: Always strictly filters audience == 'customer' (D17).
        """
        top_k = k or settings.RAG_TOP_K
        if not self._documents or self._matrix is None:
            self.load_index()
            if not self._documents or self._matrix is None:
                return []

        query_vec = np.array(embedding_service.embed_text(query), dtype=np.float32)
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        # Compute cosine similarities (dot product with unit vectors)
        # Cosine distance = 1.0 - cosine_similarity
        similarities = np.dot(self._matrix, query_vec)
        distances = 1.0 - similarities

        # Rank indices by distance ascending
        ranked_indices = np.argsort(distances)
        hits: List[Hit] = []

        for idx in ranked_indices:
            doc = self._documents[idx]
            meta = doc.get("meta", {})

            # Mandatory defense-in-depth: customer audience only
            if meta.get("audience") != "customer":
                continue

            dist = float(distances[idx])

            # Optional branch boosting if branch_id is specified
            if branch_id and meta.get("branch_id") == branch_id:
                dist = max(0.0, dist - 0.05)

            hits.append(
                Hit(
                    id=doc["id"],
                    text=doc["text"],
                    meta=meta,
                    distance=round(dist, 4)
                )
            )

            if len(hits) >= top_k:
                break

        return hits

    def is_relevant(self, hits: List[Hit], cutoff: Optional[float] = None) -> bool:
        """
        Returns True if at least one hit meets the distance cutoff.
        """
        threshold = cutoff or settings.RAG_DISTANCE_CUTOFF
        if not hits:
            return False
        return hits[0].distance <= threshold


retriever = KnowledgeRetriever()
