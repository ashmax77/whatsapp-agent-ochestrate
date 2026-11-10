"""
Hybrid retriever (2Retrieve+chatbot.ipynb, sections 3-8).

  load_index()   reads the manifest (index_info.json) and hot-swaps to a new build
                 without a restart; it always embeds queries with the backend
                 that built the index, so vector spaces can never disagree.
  RBAC           each role may only search certain top-level folders. Filtering
                 happens during the search, so restricted chunks never reach the LLM.
  hybrid search  dense vector search (meaning) + BM25 keyword search (exact names,
                 promo codes such as STUDENT15), merged without repeats.
  rerank         scores every candidate against the question and drops anything
                 below MIN_RELEVANCE_SCORE. Off-topic questions return no hits, so
                 the agent never calls the LLM for them.
"""
import json
import math
import re
import logging
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel
from app.config import settings
from app.rag.embeddings import embedding_service, LOCAL_BACKEND
from app.rag.text import tokenize  # re-exported for callers/tests

log = logging.getLogger("brain.retriever")

LEGACY_INDEX_FILE = settings.CHROMA_PATH / "kb_customer.json"
INDEX_DATA_FILE = "index.json"

# Fusion weights (semantic, keyword). The local hash embedder is much weaker than
# an API model, so keyword evidence counts for more when the index was built locally.
FUSION_WEIGHTS = {"local": (0.35, 0.65), "api": (0.55, 0.45)}


class BM25Okapi:
    """Small, dependency-free Okapi BM25 (same scoring as the rank_bm25 package)."""

    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75, epsilon: float = 0.25):
        self.k1, self.b = k1, b
        self.doc_freqs = [Counter(doc) for doc in corpus]
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = (sum(self.doc_len) / len(corpus)) if corpus else 0.0
        df: Counter = Counter()
        for doc in corpus:
            df.update(set(doc))
        n = len(corpus)
        idf = {term: math.log(n - freq + 0.5) - math.log(freq + 0.5) for term, freq in df.items()}
        positive = [v for v in idf.values() if v > 0]
        floor = epsilon * (sum(idf.values()) / len(idf)) if idf else 0.0
        if positive:
            floor = max(floor, 0.0)
        self.idf = {t: (v if v > 0 else floor) for t, v in idf.items()}

    def get_scores(self, query: List[str]) -> np.ndarray:
        scores = np.zeros(len(self.doc_freqs), dtype=np.float32)
        if not self.avgdl:
            return scores
        for term in set(query):
            idf = self.idf.get(term)
            if not idf:
                continue
            for i, freqs in enumerate(self.doc_freqs):
                tf = freqs.get(term)
                if tf:
                    denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                    scores[i] += idf * tf * (self.k1 + 1) / denom
        return scores


class Hit(BaseModel):
    id: str
    text: str
    meta: Dict[str, Any]
    distance: float  # Cosine distance: 0.0 (identical) to 2.0 (opposite); 1.0 if unknown
    score: float = 0.0  # Rerank relevance score (higher is better)


class _IndexState(BaseModel):
    """Everything one build needs. Swapped in as a whole, never half old / half new."""
    model_config = {"arbitrary_types_allowed": True}

    index_path: Optional[str] = None
    manifest_mtime: float = 0.0
    backend: str = LOCAL_BACKEND
    documents: List[Dict[str, Any]] = []
    matrix: Optional[np.ndarray] = None
    bm25: Optional[BM25Okapi] = None


class _CrossEncoderReranker:
    """Optional notebook-style cross-encoder. Enabled only when RERANKER_MODEL is set."""

    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder  # optional dependency
        self.model = CrossEncoder(model_name)

    def scores(self, query: str, texts: List[str]) -> List[float]:
        return [float(s) for s in self.model.predict([(query, t) for t in texts])]


class KnowledgeRetriever:
    def __init__(self, index_info_file: Optional[Path] = None, legacy_index_file: Optional[Path] = None):
        self.index_info_file = index_info_file or settings.INDEX_INFO_FILE
        self.legacy_index_file = legacy_index_file or LEGACY_INDEX_FILE
        self._state = _IndexState()
        self._query_api_failed = False
        self._cross_encoder = None
        if settings.RERANKER_MODEL:
            try:
                self._cross_encoder = _CrossEncoderReranker(settings.RERANKER_MODEL)
                log.info("Cross-encoder reranker enabled: %s", settings.RERANKER_MODEL)
            except Exception as e:
                log.warning("Cross-encoder unavailable (%s). Using built-in fusion reranker.", e)
        self.load_index()

    # ------------------------------------------------------------------
    # Index loading / hot swap
    # ------------------------------------------------------------------
    @property
    def index_path(self) -> Optional[str]:
        return self._state.index_path

    @property
    def document_count(self) -> int:
        return len(self._state.documents)

    def load_index(self, force: bool = False):
        """Opens the build named in the manifest. Cheap no-op if nothing changed."""
        if self.index_info_file.exists():
            mtime = self.index_info_file.stat().st_mtime
            if not force and mtime == self._state.manifest_mtime and self._state.index_path:
                return
            try:
                info = json.loads(self.index_info_file.read_text(encoding="utf-8"))
                if not force and info["index_path"] == self._state.index_path:
                    self._state.manifest_mtime = mtime
                    return
                data_file = self.index_info_file.parent / info["index_path"] / INDEX_DATA_FILE
                documents = json.loads(data_file.read_text(encoding="utf-8"))
                self._swap(documents, info["index_path"], info.get("embedding_backend", LOCAL_BACKEND), mtime)
                log.info("Opened %s with %d chunks (backend %s)", info["index_path"], len(documents),
                         self._state.backend)
            except Exception as e:
                # Keep serving the build we already have rather than going dark
                log.error("Failed to open build from manifest (%s). Keeping current build.", e)
            return

        if self.legacy_index_file.exists() and self._state.index_path != "legacy":
            try:
                documents = json.loads(self.legacy_index_file.read_text(encoding="utf-8"))
                # The legacy file does not record its backend, so its vector space is
                # unknown: serve it with keyword search only rather than risk a mismatch.
                self._swap(documents, "legacy", "legacy-unknown", 0.0)
                log.warning("No manifest found; using legacy index %s. Run: python -m app.rag.ingest",
                            self.legacy_index_file)
            except Exception as e:
                log.error("Failed to load legacy index: %s", e)
            return

        if not self._state.index_path:
            log.warning("No knowledge index found at %s. Run: python -m app.rag.ingest", self.index_info_file)

    def _swap(self, documents: List[Dict[str, Any]], index_path: str, backend: str, mtime: float):
        matrix = None
        if documents:
            matrix = np.array([d["vector"] for d in documents], dtype=np.float32)
        bm25 = BM25Okapi([tokenize(d["text"]) for d in documents]) if documents else None
        self._state = _IndexState(
            index_path=index_path, manifest_mtime=mtime, backend=backend,
            documents=documents, matrix=matrix, bm25=bm25,
        )
        self._query_api_failed = False

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------
    @staticmethod
    def allowed_folders(role: str) -> List[str]:
        """Unknown roles get the lowest (customer) access."""
        return settings.ROLE_ACCESS.get(role, settings.ROLE_ACCESS["customer"])

    @staticmethod
    def _is_allowed(meta: Dict[str, Any], folders: List[str], role: str) -> bool:
        top = str(meta.get("folder", "")).split("/")[0]
        if top not in folders:
            return False
        # Defense-in-depth (D17): non-customer audience only for roles granted internal/
        if meta.get("audience") != "customer" and "internal" not in folders:
            return False
        return True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _query_vector(self, query: str) -> Optional[np.ndarray]:
        state = self._state
        if state.matrix is None or self._query_api_failed:
            return None
        if state.backend != LOCAL_BACKEND and not state.backend.startswith("api:"):
            return None  # unknown vector space (legacy / older local version)
        try:
            vec = np.array(embedding_service.embed_with_backend(query, state.backend), dtype=np.float32)
        except Exception as e:
            # Index was built with the API but it is unreachable now: keyword search still works
            log.warning("Query embedding failed for backend %s (%s). Using keyword search only.", state.backend, e)
            self._query_api_failed = True
            return None
        if vec.shape[0] != state.matrix.shape[1]:
            log.error("Query vector size %d does not match index size %d.", vec.shape[0], state.matrix.shape[1])
            return None
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def _candidates(self, query: str, allowed: List[int], n: int) -> Dict[int, Dict[str, float]]:
        """Hybrid search: union of the top-n vector and top-n keyword results."""
        state = self._state
        found: Dict[int, Dict[str, float]] = {}
        if not allowed:
            return found
        idx = np.array(allowed)

        qvec = self._query_vector(query)
        sims = None
        if qvec is not None:
            sims = state.matrix[idx] @ qvec
            for j in np.argsort(-sims)[:n]:
                found.setdefault(int(idx[j]), {})

        bm25 = state.bm25.get_scores(tokenize(query)) if state.bm25 else np.zeros(len(state.documents))
        kw = bm25[idx]
        for j in np.argsort(-kw)[:n]:
            if kw[j] > 0:
                found.setdefault(int(idx[j]), {})

        for doc_i in found:
            j = allowed.index(doc_i)
            found[doc_i]["cos"] = float(sims[j]) if sims is not None else 0.0
            found[doc_i]["bm25"] = float(bm25[doc_i])
        return found

    def _fusion_score(self, cos: float, bm25: float, has_vectors: bool) -> float:
        """
        Built-in reranker: semantic similarity blended with a saturated keyword score.
        bm25 / (bm25 + 4) maps 0..inf onto 0..1, so one rare exact match (a promo
        code, an item name) counts strongly without dominating everything.
        """
        kw = bm25 / (bm25 + 4.0) if bm25 > 0 else 0.0
        if not has_vectors:
            return kw
        w_sem, w_kw = FUSION_WEIGHTS["local" if self._state.backend.startswith("local") else "api"]
        return w_sem * max(cos, 0.0) + w_kw * kw

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        branch_id: Optional[str] = None,
        role: str = "customer",
        min_score: Optional[float] = None,
    ) -> List[Hit]:
        """
        Hybrid search -> rerank -> relevance gate. Returns at most k hits that the
        role is allowed to see, best first. An empty list means "not answerable".
        """
        self.load_index()
        state = self._state
        if not state.documents:
            return []

        top_k = k or settings.RAG_TOP_K
        folders = self.allowed_folders(role)
        allowed = [i for i, d in enumerate(state.documents) if self._is_allowed(d.get("meta", {}), folders, role)]
        found = self._candidates(query, allowed, settings.RAG_SEARCH_RESULTS)
        if not found:
            return []

        order = list(found.keys())
        has_vectors = any(s["cos"] != 0.0 for s in found.values())
        if self._cross_encoder is not None:
            texts = [state.documents[i]["text"] for i in order]
            scores = self._cross_encoder.scores(query, texts)
            cutoff = settings.RERANKER_MIN_SCORE if min_score is None else min_score
        else:
            scores = [self._fusion_score(found[i]["cos"], found[i]["bm25"], has_vectors) for i in order]
            cutoff = settings.MIN_RELEVANCE_SCORE if min_score is None else min_score

        hits: List[Hit] = []
        for doc_i, score in zip(order, scores):
            doc = state.documents[doc_i]
            meta = doc.get("meta", {})
            # Small boost for the customer's own outlet
            if branch_id and meta.get("branch_id") == branch_id:
                score += 0.05
            cos = found[doc_i]["cos"]
            hits.append(Hit(
                id=doc["id"], text=doc["text"], meta=meta,
                distance=round(1.0 - cos, 4) if has_vectors else 1.0,
                score=round(float(score), 4),
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return [h for h in hits if h.score >= cutoff][:top_k]

    def is_relevant(self, hits: List[Hit], cutoff: Optional[float] = None) -> bool:
        """
        Returns True if the best hit clears the relevance cutoff.
        """
        threshold = settings.MIN_RELEVANCE_SCORE if cutoff is None else cutoff
        return bool(hits) and hits[0].score >= threshold


retriever = KnowledgeRetriever()
