import re
import json
import yaml
import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from app.config import settings
from app.services.menu_repo import menu_repo

log = logging.getLogger("brain.kb_loader")

# Chunk id suffix used for the text that sits between the "# Title" and the first "##".
# generate_slug() never produces "_", so this can never collide with a real heading slug.
INTRO_SLUG = "_intro"
SUMMARY_FILE = "_summary"


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


def clean_text(text: str) -> str:
    """
    Removes layout noise that pollutes embeddings (1Ingestion.ipynb, section 4):
    signature underscores, standalone '---' divider lines and runs of blank lines.
    Headings, names and titles are kept.
    """
    text = text.replace("\r\n", "\n")
    text = re.sub(r"_{5,}", "", text)
    text = re.sub(r"^---\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Recursive character splitter: tries paragraph, line, sentence and word
    boundaries in that order, then packs pieces up to chunk_size with overlap.
    """
    if len(text) <= chunk_size:
        return [text]

    pieces = [text]
    for sep in ("\n\n", "\n", ". ", " "):
        if all(len(p) <= chunk_size for p in pieces):
            break
        next_pieces: List[str] = []
        for p in pieces:
            if len(p) <= chunk_size:
                next_pieces.append(p)
                continue
            parts = p.split(sep)
            next_pieces.extend(part + sep for part in parts[:-1])
            next_pieces.append(parts[-1])
        pieces = [p for p in next_pieces if p]

    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > chunk_size:
            chunks.append(current.strip())
            # Carry the tail of the previous chunk forward, starting on a word boundary
            tail = current[-overlap:] if overlap > 0 else ""
            if " " in tail:
                tail = tail[tail.index(" ") + 1:]
            current = tail
        current += piece
    if current.strip():
        chunks.append(current.strip())
    return chunks


def context_header(folder: str, doc_title: str, section: str) -> str:
    """Every chunk states what it is about, so it survives being read on its own."""
    return f"Document: {folder} - {doc_title}\nSection: {section}\n\n"


class KBLoader:
    def __init__(
        self,
        kb_path: Optional[Path] = None,
        exclude_dirs: Optional[List[str]] = None,
        exclude_files: Optional[List[str]] = None,
        branches_path: Optional[Path] = None,
    ):
        self.kb_path = kb_path or settings.KB_PATH
        self.exclude_dirs = exclude_dirs or settings.KB_EXCLUDE_DIRS
        self.exclude_files = exclude_files or settings.KB_EXCLUDE_FILES
        self.branches_path = branches_path or settings.BRANCHES_FILE_PATH
        self.skipped_files: List[str] = []

    def load_chunks(
        self,
        include_internal: bool = False,
        include_summaries: bool = True,
    ) -> List[KnowledgeChunk]:
        """
        Recursively walks KB_PATH, parses markdown into chunks, and extracts metadata.
        By default (include_internal=False), internal directories are completely skipped.
        Unreadable files are skipped and recorded in self.skipped_files instead of
        aborting the whole run.
        """
        self.skipped_files = []
        if not self.kb_path.exists():
            log.warning("Knowledge base path does not exist: %s", self.kb_path)
            return []

        chunks: List[KnowledgeChunk] = []
        seen_ids: Dict[str, str] = {}

        # rglob("*.md") ignores loose non-markdown files by construction
        for md_file in sorted(self.kb_path.rglob("*.md")):
            rel_path = md_file.relative_to(self.kb_path)
            rel_parts = rel_path.parts

            # Check directory exclusions
            if not include_internal and any(ex in rel_parts[:-1] for ex in self.exclude_dirs):
                continue

            # Check file exclusions
            if md_file.name in self.exclude_files:
                continue

            raw_content = self._read_file(md_file, rel_path)
            if raw_content is None:
                continue

            file_chunks = self._process_file(md_file, rel_path, raw_content)
            for chunk in file_chunks:
                self._register(chunk, str(rel_path), seen_ids, chunks)

        if include_summaries:
            for chunk in self.build_summary_chunks():
                self._register(chunk, "<summary>", seen_ids, chunks)

        if self.skipped_files:
            log.warning("Skipped %d unreadable file(s): %s", len(self.skipped_files), self.skipped_files)
        log.info("Loaded %d knowledge chunks from %s", len(chunks), self.kb_path)
        return chunks

    @staticmethod
    def _register(chunk: KnowledgeChunk, origin: str, seen_ids: Dict[str, str], out: List[KnowledgeChunk]):
        if chunk.id in seen_ids:
            raise ValueError(
                f"Duplicate chunk id '{chunk.id}' detected in '{origin}' (previously seen in '{seen_ids[chunk.id]}')"
            )
        seen_ids[chunk.id] = origin
        out.append(chunk)

    def _read_file(self, file_path: Path, rel_path: Path) -> Optional[str]:
        """Safe read: a single bad file is reported and skipped, never fatal."""
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log.warning("Skipping non-UTF-8 file: %s", rel_path)
        except OSError as e:
            log.warning("Skipping unreadable file %s: %s", rel_path, e)
        self.skipped_files.append(rel_path.as_posix())
        return None

    @staticmethod
    def _split_sections(body: str) -> Tuple[str, str, List[Tuple[str, str, str]]]:
        """
        Splits a markdown body into (doc_title, intro_text, sections) where each
        section is (h2_heading, h3_heading_or_empty, section_text_with_heading).
        """
        doc_title = ""
        h1 = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
        if h1:
            doc_title = h1.group(1).strip()

        raw_h2 = re.split(r"\n(?=##\s+)", "\n" + body)
        intro = raw_h2[0].strip()
        # Drop the "# Title" line from the intro; it is carried by the context header
        intro = re.sub(r"^#\s+.+$", "", intro, flags=re.MULTILINE).strip()

        sections: List[Tuple[str, str, str]] = []
        for raw in raw_h2[1:]:
            raw = raw.strip()
            if not raw.startswith("## "):
                continue
            h2_heading = raw.splitlines()[0].lstrip("#").strip()
            parts = re.split(r"\n(?=###\s+)", raw)
            sections.append((h2_heading, "", parts[0].strip()))
            for sub in parts[1:]:
                sub = sub.strip()
                h3_heading = sub.splitlines()[0].lstrip("#").strip()
                sections.append((h2_heading, h3_heading, sub))
        return doc_title, intro, sections

    def _process_file(self, file_path: Path, rel_path: Path, raw_content: Optional[str] = None) -> List[KnowledgeChunk]:
        if raw_content is None:
            raw_content = file_path.read_text(encoding="utf-8")

        front_matter, body = parse_front_matter(raw_content)
        body = clean_text(body)
        audience = front_matter.get("audience", "customer")
        last_updated = str(front_matter.get("last_updated", ""))

        folder_name = rel_path.parent.as_posix()
        file_stem = file_path.stem
        id_prefix = file_stem if folder_name == "." else f"{folder_name}/{file_stem}"

        doc_title, intro, sections = self._split_sections(body)
        doc_title = doc_title or file_stem.replace("-", " ").title()

        units: List[Tuple[str, str, str]] = []  # (slug, heading, text)
        if len(intro) >= settings.MIN_CHUNK_SIZE:
            units.append((INTRO_SLUG, doc_title, intro))
        for h2_heading, h3_heading, text in sections:
            # Title-only sections hold no information (1Ingestion.ipynb, section 5)
            if len(text) < settings.MIN_CHUNK_SIZE:
                continue
            slug = generate_slug(h2_heading)
            heading = h2_heading
            if h3_heading:
                slug = f"{slug}/{generate_slug(h3_heading)}"
                heading = h3_heading
            units.append((slug, heading, text))

        chunks: List[KnowledgeChunk] = []
        for slug, heading, text in units:
            # Link item_id if in menu files and matches an item in menu_repo
            matched_item_id = None
            if "menu" in folder_name and slug != INTRO_SLUG:
                matched = menu_repo.find_by_name(heading)
                if matched:
                    matched_item_id = matched.id

            # Determine branch_id for branch directory files
            branch_id = None
            if "branches" in folder_name:
                if "colombo-07" in file_stem or "colombo" in slug:
                    branch_id = "colombo07"
                elif "nugegoda" in file_stem or "nugegoda" in slug:
                    branch_id = "nugegoda"
                elif "kandy" in file_stem or "kandy" in slug:
                    branch_id = "kandy"

            parts = split_by_size(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
            for idx, part in enumerate(parts, start=1):
                chunk_id = f"{id_prefix}#{slug}"
                if len(parts) > 1:
                    chunk_id = f"{chunk_id}-part{idx}"

                chunk_meta = {
                    "audience": audience,
                    "folder": folder_name,
                    "file": file_stem,
                    "doc_title": doc_title,
                    "title": heading,
                    "section": heading,
                    "item_id": matched_item_id,
                    "branch_id": branch_id,
                    "last_updated": last_updated,
                    "doc_type": "section",
                }
                chunks.append(
                    KnowledgeChunk(
                        id=chunk_id,
                        text=context_header(folder_name, doc_title, heading) + part,
                        meta=chunk_meta,
                    )
                )

        return chunks

    # ------------------------------------------------------------------
    # Summary documents (1Ingestion.ipynb, section 6): one chunk that sees
    # everything, so "which pizzas are vegetarian?" is answerable at all.
    # Prices are deliberately excluded (D3): money comes from menu.json via code.
    # ------------------------------------------------------------------
    def build_summary_chunks(self) -> List[KnowledgeChunk]:
        chunks: List[KnowledgeChunk] = []
        today = date.today().isoformat()

        menu_chunk = self._menu_summary(today)
        if menu_chunk:
            chunks.append(menu_chunk)

        branch_chunk = self._branch_summary(today)
        if branch_chunk:
            chunks.append(branch_chunk)

        offers_chunk = self._offers_summary(today)
        if offers_chunk:
            chunks.append(offers_chunk)

        return chunks

    @staticmethod
    def _summary_meta(folder: str, title: str, today: str) -> Dict[str, Any]:
        return {
            "audience": "customer",
            "folder": folder,
            "file": SUMMARY_FILE,
            "doc_title": title,
            "title": title,
            "section": title,
            "item_id": None,
            "branch_id": None,
            "last_updated": today,
            "doc_type": "summary",
        }

    def menu_summary_rows(self) -> List[Dict[str, Any]]:
        rows = []
        for item in menu_repo.get_all_items():
            rows.append({
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "vegetarian": "yes" if item.veg else "no",
                "allergens": ", ".join(item.allergens) or "none declared",
                "available": "yes" if item.available else "no",
            })
        order = {"pizza": 0, "side": 1, "dessert": 2, "beverage": 3}
        rows.sort(key=lambda r: (order.get(r["category"], 9), r["name"]))
        return rows

    def _menu_summary(self, today: str) -> Optional[KnowledgeChunk]:
        rows = self.menu_summary_rows()
        if not rows:
            return None
        title = f"Summary table of all {len(rows)} menu items"
        lines = [
            context_header("menu", title, "Use this table for questions about the whole menu, "
                           "such as which items are vegetarian or contain an allergen.").rstrip(),
            "",
            "| Item | Category | Vegetarian | Allergens | Available |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(f"| {r['name']} | {r['category']} | {r['vegetarian']} | {r['allergens']} | {r['available']} |")
        return KnowledgeChunk(id=f"menu/{SUMMARY_FILE}#all-items", text="\n".join(lines),
                              meta=self._summary_meta("menu", title, today))

    def _branch_summary(self, today: str) -> Optional[KnowledgeChunk]:
        if not self.branches_path.exists():
            return None
        try:
            data = json.loads(self.branches_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Could not read branches for summary: %s", e)
            return None
        branches = data.get("branches", [])
        if not branches:
            return None
        title = f"Summary table of all {len(branches)} outlets"
        lines = [
            context_header("branches", title, "Use this table to compare outlets, opening hours "
                           "and the areas each outlet delivers to.").rstrip(),
            "",
            "| Outlet | Opens | Closes | Last delivery order | Delivery radius | Areas served |",
            "|---|---|---|---|---|---|",
        ]
        for b in branches:
            hours = b.get("hours", {})
            areas = ", ".join(a.title() for a in b.get("area_aliases", []))
            lines.append(
                f"| {b.get('name', b.get('id'))} | {hours.get('open', '?')} | {hours.get('close', '?')} | "
                f"{b.get('last_delivery_order', '?')} | {b.get('max_km', '?')} km | {areas} |"
            )
        return KnowledgeChunk(id=f"branches/{SUMMARY_FILE}#all-outlets", text="\n".join(lines),
                              meta=self._summary_meta("branches", title, today))

    def _offers_summary(self, today: str) -> Optional[KnowledgeChunk]:
        offers_file = self.kb_path / "offers" / "current-offers.md"
        if not offers_file.exists():
            return None
        try:
            _, body = parse_front_matter(offers_file.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            return None
        headings = [h.strip() for h in re.findall(r"^##\s+(.+)$", body, flags=re.MULTILINE)]
        active = [h for h in headings if not h.lower().startswith(("upcoming", "how offers"))]
        if not active:
            return None
        title = f"Summary list of all {len(active)} current offers"
        lines = [
            context_header("offers", title, "Use this list for questions about which offers or "
                           "promo codes are available right now.").rstrip(),
            "",
        ]
        lines.extend(f"- {h}" for h in active)
        return KnowledgeChunk(id=f"offers/{SUMMARY_FILE}#current-offers", text="\n".join(lines),
                              meta=self._summary_meta("offers", title, today))


kb_loader = KBLoader()
