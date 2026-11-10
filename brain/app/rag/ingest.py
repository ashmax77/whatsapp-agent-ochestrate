"""
Knowledge base ingestion with zero-downtime blue/green builds (1Ingestion.ipynb, sections 7-9).

    python -m app.rag.ingest            # build a new index and switch to it
    python -m app.rag.ingest --local    # force the offline local embedding backend

Flow:
  1. Load + clean + chunk the customer KB (internal/ is never loaded).
  2. Pre-flight checks. Any failure stops here, before embedding costs are spent.
  3. Embed every chunk with ONE backend (never a mix of vector spaces).
  4. Write everything into a new folder  data/chroma/build_YYYYMMDD_HHMMSS/.
     The live build is never touched, so a failure leaves the bot working.
  5. Read the build back and verify the saved count equals the chunk count.
  6. Atomically switch the manifest (index_info.json) to the new build.
  7. Prune old builds, keeping BUILDS_TO_KEEP (newest = live, previous = backup).
"""
import sys
import csv
import json
import shutil
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from app.config import settings
from app.rag.kb_loader import KBLoader, KnowledgeChunk, kb_loader
from app.rag.embeddings import embedding_service, LOCAL_BACKEND
from app.rag.validate_kb import preflight_check

log = logging.getLogger("ingest")

INDEX_DATA_FILE = "index.json"
MENU_SUMMARY_FILE = "menu_summary.csv"


class IngestError(RuntimeError):
    pass


def _write_json_atomic(path: Path, data: Dict[str, Any]):
    """Write to a .tmp file, then rename over the target in a single step."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def prune_builds(chroma_path: Path, keep: int, live_build: Optional[str] = None) -> List[str]:
    """
    Deletes all but the newest `keep` builds. The live build is never deleted.
    ignore_errors=True: if Windows still holds a file open, we retry next time.
    """
    all_builds = sorted(p for p in chroma_path.glob("build_*") if p.is_dir())
    old_builds = all_builds[:-keep] if keep > 0 else all_builds
    removed = []
    for old in old_builds:
        if live_build and old.name == live_build:
            continue
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed


def _unique_build_folder(chroma_path: Path) -> Path:
    base = datetime.now().strftime("build_%Y%m%d_%H%M%S")
    folder = chroma_path / base
    n = 1
    while folder.exists():
        folder = chroma_path / f"{base}_{n}"
        n += 1
    return folder


def ingest_kb(
    rebuild: bool = True,
    chroma_path: Optional[Path] = None,
    loader: Optional[KBLoader] = None,
    prefer_local: bool = False,
    builds_to_keep: Optional[int] = None,
) -> int:
    """
    Builds a new customer index and switches the manifest to it.
    Returns 0 on success, 1 on failure (the previous build stays live on failure).
    `rebuild` is kept for CLI compatibility; every run is a fresh blue/green build.
    """
    chroma_path = chroma_path or settings.CHROMA_PATH
    loader = loader or kb_loader
    keep = builds_to_keep if builds_to_keep is not None else settings.BUILDS_TO_KEEP
    manifest_path = chroma_path / settings.INDEX_INFO_FILE.name
    chroma_path.mkdir(parents=True, exist_ok=True)

    log.info("Starting Knowledge Base Ingestion...")

    # 1. Load. internal/ is excluded at load time (first layer of D17)
    try:
        chunks: List[KnowledgeChunk] = loader.load_chunks(include_internal=False)
    except ValueError as e:
        log.error("Chunking failed: %s. Keeping the current build.", e)
        return 1

    # 2. Pre-flight, before any embedding cost
    errors = preflight_check(chunks)
    internal_count = sum(1 for e in errors if "leak" in e)
    print(f"internal chunks indexed: {internal_count}")
    if errors:
        log.error("Pre-flight FAILED with %d error(s). Keeping the current build.", len(errors))
        for err in errors:
            log.error("  x %s", err)
        return 1

    sizes = [len(c.text) for c in chunks]
    log.info("Pre-flight OK: %d chunks, smallest %d chars, largest %d chars", len(chunks), min(sizes), max(sizes))

    # 3. Embed with a single backend
    backend = embedding_service.resolve_backend(prefer_local=prefer_local)
    log.info("Embedding backend: %s", backend)
    documents: List[Dict[str, Any]] = []
    folder_counts: Dict[str, int] = defaultdict(int)
    try:
        for chunk in chunks:
            vec = embedding_service.embed_with_backend(chunk.text, backend)
            documents.append({"id": chunk.id, "text": chunk.text, "meta": chunk.meta, "vector": vec})
            folder_counts[chunk.meta.get("folder", "root")] += 1
    except Exception as e:
        log.error("Embedding failed part-way (%s). Keeping the current build.", e)
        return 1

    dims = {len(d["vector"]) for d in documents}
    if len(dims) != 1:
        log.error("Mixed embedding sizes %s. Keeping the current build.", sorted(dims))
        return 1

    # 4. Write into a brand new build folder
    build_folder = _unique_build_folder(chroma_path)
    try:
        build_folder.mkdir(parents=True)
        (build_folder / INDEX_DATA_FILE).write_text(json.dumps(documents), encoding="utf-8")

        rows = loader.menu_summary_rows()
        if rows:
            with open(build_folder / MENU_SUMMARY_FILE, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

        # 5. Verify by reading back what was saved
        saved = json.loads((build_folder / INDEX_DATA_FILE).read_text(encoding="utf-8"))
        if len(saved) != len(chunks):
            raise IngestError(f"Expected {len(chunks)} chunks but saved {len(saved)}")
    except Exception as e:
        log.error("Build failed (%s). Keeping the current build.", e)
        shutil.rmtree(build_folder, ignore_errors=True)
        return 1

    # 6. Atomic switch
    index_info = {
        "index_path": build_folder.name,
        "embedding_backend": backend,
        "embedding_model": settings.EMBEDDING_MODEL if backend != LOCAL_BACKEND else LOCAL_BACKEND,
        "embedding_dim": dims.pop(),
        "chunk_count": len(saved),
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json_atomic(manifest_path, index_info)

    # 7. Prune, never the live build
    removed = prune_builds(chroma_path, keep, live_build=build_folder.name)

    log.info("=== Ingestion Summary ===")
    for folder, count in sorted(folder_counts.items()):
        log.info("  folder '%s': %d chunks", folder, count)
    if loader.skipped_files:
        log.warning("  skipped unreadable files: %s", loader.skipped_files)
    log.info("Total customer chunks indexed: %d", len(saved))
    log.info("Live build: %s (removed %d old build(s))", build_folder.name, len(removed))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    exit_code = ingest_kb(rebuild=True, prefer_local="--local" in sys.argv)
    sys.exit(exit_code)
