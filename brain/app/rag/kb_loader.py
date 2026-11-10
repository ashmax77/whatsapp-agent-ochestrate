import re
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.config import settings
from app.services.menu_repo import menu_repo

log = logging.getLogger("brain.kb_loader")


class KnowledgeChunk(BaseModel):
    id: str
    text: str
    meta: Dict[str, Any]


def generate_slug(text: str) -> str:
    """
    Slug rule from plan.md:
    lowercase, drop characters other than letters, digits, spaces and hyphens,
    then convert spaces to hyphens.
    Example: "Student Tuesday (code STUDENT15)" -> "student-tuesday-code-student15"
    """
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", text.strip().lower())
    slug = re.sub(r"[\s]+", "-", cleaned)
    return slug.strip("-")


def parse_front_matter(content: str) -> tuple[Dict[str, Any], str]:
    """
    Strips YAML front matter delimited by '---' at the top of markdown.
    Returns (metadata_dict, body_text).
    """
    meta: Dict[str, Any] = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw_yaml = parts[1].strip()
            body = parts[2].strip()
            try:
                meta = yaml.safe_load(raw_yaml) or {}
            except Exception as e:
                log.warning("Failed to parse YAML front matter: %s", e)

    return meta, body


class KBLoader:
    def __init__(
        self,
        kb_path: Optional[Path] = None,
        exclude_dirs: Optional[List[str]] = None,
        exclude_files: Optional[List[str]] = None
    ):
        self.kb_path = kb_path or settings.KB_PATH
        self.exclude_dirs = exclude_dirs or settings.KB_EXCLUDE_DIRS
        self.exclude_files = exclude_files or settings.KB_EXCLUDE_FILES

    def load_chunks(self, include_internal: bool = False) -> List[KnowledgeChunk]:
        """
        Recursively walks KB_PATH, parses markdown into chunks, and extracts metadata.
        By default (include_internal=False), internal directories are completely skipped.
        """
        if not self.kb_path.exists():
            log.warning("Knowledge base path does not exist: %s", self.kb_path)
            return []

        chunks: List[KnowledgeChunk] = []
        seen_ids: Dict[str, str] = {}

        for md_file in sorted(self.kb_path.rglob("*.md")):
            rel_path = md_file.relative_to(self.kb_path)
            rel_parts = rel_path.parts

            # Check directory exclusions
            if not include_internal and any(ex in rel_parts for ex in self.exclude_dirs):
                continue

            # Check file exclusions
            if md_file.name in self.exclude_files:
                continue

            file_chunks = self._process_file(md_file, rel_path)
            for chunk in file_chunks:
                if chunk.id in seen_ids:
                    raise ValueError(
                        f"Duplicate chunk id '{chunk.id}' detected in '{rel_path}' (previously seen in '{seen_ids[chunk.id]}')"
                    )
                seen_ids[chunk.id] = str(rel_path)
                chunks.append(chunk)

        log.info("Loaded %d knowledge chunks from %s", len(chunks), self.kb_path)
        return chunks

    def _process_file(self, file_path: Path, rel_path: Path) -> List[KnowledgeChunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        front_matter, body = parse_front_matter(raw_content)
        audience = front_matter.get("audience", "customer")
        last_updated = str(front_matter.get("last_updated", ""))

        folder_name = rel_path.parent.as_posix()
        file_stem = file_path.stem

        # Split on sections starting with "## "
        # Notice: lines before the first "## " (such as "# Title") are introductory and not indexed as chunks per D20
        raw_sections = re.split(r"\n(?=##\s+)", body)
        chunks: List[KnowledgeChunk] = []

        for section in raw_sections:
            section_strip = section.strip()
            if not section_strip.startswith("## "):
                continue

            # Extract heading line
            lines = section_strip.splitlines()
            heading_line = lines[0].lstrip("#").strip()
            heading_slug = generate_slug(heading_line)
            chunk_text = section_strip

            # Chunk ID: <folder path>/<file stem>#<heading slug>
            if folder_name == ".":
                chunk_id = f"{file_stem}#{heading_slug}"
            else:
                chunk_id = f"{folder_name}/{file_stem}#{heading_slug}"

            # Link item_id if in menu files and matches an item in menu_repo
            matched_item_id = None
            if "menu" in folder_name:
                matched = menu_repo.find_by_name(heading_line)
                if matched:
                    matched_item_id = matched.id

            # Determine branch_id for branch directory files
            branch_id = None
            if "branches" in folder_name:
                if "colombo-07" in file_stem or "colombo" in heading_slug:
                    branch_id = "colombo07"
                elif "nugegoda" in file_stem or "nugegoda" in heading_slug:
                    branch_id = "nugegoda"
                elif "kandy" in file_stem or "kandy" in heading_slug:
                    branch_id = "kandy"

            chunk_meta = {
                "audience": audience,
                "folder": folder_name,
                "file": file_stem,
                "title": heading_line,
                "item_id": matched_item_id,
                "branch_id": branch_id,
                "last_updated": last_updated
            }

            chunks.append(
                KnowledgeChunk(
                    id=chunk_id,
                    text=chunk_text,
                    meta=chunk_meta
                )
            )

        return chunks


kb_loader = KBLoader()

