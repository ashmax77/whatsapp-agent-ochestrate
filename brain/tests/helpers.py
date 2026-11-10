"""Shared fixtures: build a throwaway blue/green index so tests never touch data/chroma."""
import logging
import shutil
import tempfile
from pathlib import Path
from app.rag.ingest import ingest_kb
from app.rag.kb_loader import KBLoader
from app.rag.retriever import KnowledgeRetriever


class TempIndex:
    """Builds the real customer KB into a temp folder with the offline local backend."""

    def __init__(self, loader: KBLoader = None):
        self.dir = Path(tempfile.mkdtemp(prefix="kb_test_"))
        self.loader = loader or KBLoader()
        logging.disable(logging.CRITICAL)
        try:
            code = ingest_kb(chroma_path=self.dir, loader=self.loader, prefer_local=True)
        finally:
            logging.disable(logging.NOTSET)
        if code != 0:
            raise RuntimeError("Test index build failed")
        self.manifest = self.dir / "index_info.json"

    def retriever(self) -> KnowledgeRetriever:
        return KnowledgeRetriever(index_info_file=self.manifest, legacy_index_file=self.dir / "none.json")

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class OfflineLLM:
    """LLM stub that always fails, exercising the deterministic / fallback paths."""

    def complete(self, *args, **kwargs):
        raise RuntimeError("LLM offline (test stub)")

