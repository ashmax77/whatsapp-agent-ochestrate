import sys
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any
import numpy as np
from app.config import settings
from app.rag.kb_loader import kb_loader, KnowledgeChunk
from app.rag.embeddings import embedding_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("ingest")

INDEX_FILE = settings.CHROMA_PATH / "kb_customer.json"


def ingest_kb(rebuild: bool = True) -> int:
    """
    Ingests customer knowledge chunks into the vector store index.
    Always strictly excludes internal/ documents.
    """
    settings.CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    log.info("Starting Knowledge Base Ingestion...")
    chunks: List[KnowledgeChunk] = kb_loader.load_chunks(include_internal=False)

    folder_counts = defaultdict(int)
    internal_count = 0

    documents: List[Dict[str, Any]] = []

    for chunk in chunks:
        folder = chunk.meta.get("folder", "root")
        audience = chunk.meta.get("audience", "")

        if audience != "customer" or "internal" in folder:
            internal_count += 1
            continue

        folder_counts[folder] += 1
        vec = embedding_service.embed_text(chunk.text)

        documents.append({
            "id": chunk.id,
            "text": chunk.text,
            "meta": chunk.meta,
            "vector": vec
        })

    # Save to persistent storage
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2)

    log.info("=== Ingestion Summary ===")
    for folder, count in sorted(folder_counts.items()):
        log.info("  folder '%s': %d chunks", folder, count)

    log.info("Total customer chunks indexed: %d", len(documents))
    print(f"internal chunks indexed: {internal_count}")

    if internal_count > 0:
        log.error("CRITICAL SECURITY VIOLATION: Internal chunks were found in customer index!")
        return 1

    log.info("Ingestion completed successfully at %s", INDEX_FILE)
    return 0


if __name__ == "__main__":
    rebuild_flag = "--rebuild" in sys.argv
    exit_code = ingest_kb(rebuild=rebuild_flag)
    sys.exit(exit_code)
