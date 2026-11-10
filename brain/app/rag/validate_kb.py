import sys
import re
import yaml
import logging
from pathlib import Path
from typing import List, Tuple
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("validate_kb")


def check_front_matter(md_file: Path, kb_path: Path) -> List[str]:
    errors = []
    rel_path = md_file.relative_to(kb_path)
    rel_str = str(rel_path).replace("\\", "/")

    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        return [f"[{rel_str}] Missing front matter (must start with '---')"]

    parts = content.split("---", 2)
    if len(parts) < 3:
        return [f"[{rel_str}] Malformed front matter (must be enclosed in '---')"]

    raw_yaml = parts[1].strip()
    try:
        data = yaml.safe_load(raw_yaml) or {}
    except Exception as e:
        return [f"[{rel_str}] Invalid YAML front matter: {e}"]

    audience = data.get("audience")
    if audience not in ["customer", "internal"]:
        errors.append(f"[{rel_str}] Front matter 'audience' must be 'customer' or 'internal' (got '{audience}')")

    is_under_internal = "internal/" in rel_str or rel_str.startswith("internal/")
    if is_under_internal and audience != "internal":
        errors.append(f"[{rel_str}] File is under internal/ but audience is '{audience}'")
    elif not is_under_internal and audience != "customer":
        errors.append(f"[{rel_str}] File is outside internal/ but audience is '{audience}'")

    if "last_updated" not in data:
        errors.append(f"[{rel_str}] Front matter missing 'last_updated' date")

    return errors


def check_sections(md_file: Path, kb_path: Path) -> Tuple[List[str], List[str]]:
    errors = []
    warnings = []
    rel_path = md_file.relative_to(kb_path)
    rel_str = str(rel_path).replace("\\", "/")

    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Split by ## sections
    sections = re.split(r"\n(?=##\s+)", content)
    for section in sections:
        section = section.strip()
        if not section.startswith("## "):
            continue

        lines = section.splitlines()
        heading = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
        words = body.split()
        word_count = len(words)

        # Word count check: 20-120 words recommended, warn 120-150, error above 150
        if word_count > 150:
            errors.append(f"[{rel_str} -> '{heading}'] Section exceeds 150 words limit ({word_count} words)")
        elif word_count > 120:
            warnings.append(f"[{rel_str} -> '{heading}'] Section exceeds recommended 120 words ({word_count} words)")

    return errors, warnings


def check_pii(md_file: Path, kb_path: Path) -> List[str]:
    errors = []
    rel_path = md_file.relative_to(kb_path)
    rel_str = str(rel_path).replace("\\", "/")

    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for email addresses
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    emails = re.findall(email_pattern, content)
    if emails:
        errors.append(f"[{rel_str}] Disallowed email pattern detected: {emails}")

    # Check for Sri Lankan NIC patterns (9 digits followed by V/X, or modern 12 digits)
    nic_pattern_old = r"\b\d{9}[VvXx]\b"
    nic_pattern_new = r"\b\d{12}\b"
    if re.search(nic_pattern_old, content) or re.search(nic_pattern_new, content):
        errors.append(f"[{rel_str}] Disallowed NIC-like number detected")

    # Check for real phone numbers (allowed sample range: +94 11 000 xxxx and +94 81 000 xxxx)
    phone_pattern = r"\+94\s*\d{2}\s*\d{3}\s*\d{4}"
    for match in re.finditer(phone_pattern, content):
        phone = match.group(0)
        # Verify it's within sample ranges: +94 11 000 or +94 81 000
        compact = re.sub(r"\s+", "", phone)
        if not (compact.startswith("+9411000") or compact.startswith("+9481000")):
            errors.append(f"[{rel_str}] Real phone number outside sample range (+94 11 000 / +94 81 000) detected: {phone}")

    return errors


REQUIRED_CHUNK_META = ("audience", "folder", "title")


def preflight_check(chunks) -> List[str]:
    """
    Checks the chunks before any embedding money is spent (1Ingestion.ipynb, section 7).
    Returns a list of errors; an empty list means the chunks are safe to embed.
    Shared by validate_kb (CLI) and ingest (build gate).
    """
    errors: List[str] = []
    if len(chunks) == 0:
        return ["No chunks were created. Check KB_PATH and the markdown headings."]

    for chunk in chunks:
        text = (chunk.text or "").strip()
        if not text:
            errors.append(f"[{chunk.id}] Empty chunk text")
        elif len(text) > settings.MAX_CHUNK_CHARS:
            errors.append(f"[{chunk.id}] Chunk is {len(text)} characters (limit {settings.MAX_CHUNK_CHARS})")

        missing = [key for key in REQUIRED_CHUNK_META if not chunk.meta.get(key)]
        if missing:
            errors.append(f"[{chunk.id}] Missing metadata: {', '.join(missing)}")

        folder = str(chunk.meta.get("folder", ""))
        if chunk.meta.get("audience") != "customer" or folder.split("/")[0] in settings.KB_EXCLUDE_DIRS:
            errors.append(f"[{chunk.id}] Non-customer chunk in customer build (audience/folder leak)")

    return errors


def validate_kb() -> bool:
    kb_path = settings.KB_PATH
    if not kb_path.exists():
        log.error("Knowledge base directory does not exist: %s", kb_path)
        return False

    all_errors = []
    all_warnings = []

    log.info("Starting Knowledge Base Validation on %s ...", kb_path)

    for md_file in sorted(kb_path.rglob("*.md")):
        # Skip top-level README.md if configured
        if md_file.name == "README.md":
            continue

        # A file that is not UTF-8 would be skipped by ingest; the validator flags it
        try:
            md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            rel_str = md_file.relative_to(kb_path).as_posix()
            all_errors.append(f"[{rel_str}] File is not valid UTF-8 (ingest would skip it)")
            continue

        fm_errors = check_front_matter(md_file, kb_path)
        all_errors.extend(fm_errors)

        sec_errors, sec_warns = check_sections(md_file, kb_path)
        all_errors.extend(sec_errors)
        all_warnings.extend(sec_warns)

        pii_errors = check_pii(md_file, kb_path)
        all_errors.extend(pii_errors)

    # Pre-flight: the exact chunks ingest would embed for the customer build
    from app.rag.kb_loader import KBLoader
    loader = KBLoader(kb_path=kb_path)
    try:
        chunks = loader.load_chunks(include_internal=False)
        all_errors.extend(preflight_check(chunks))
        log.info("Pre-flight: %d customer chunks checked", len(chunks))
    except ValueError as e:
        all_errors.append(f"Chunking failed: {e}")

    for w in all_warnings:
        log.warning(w)

    if all_errors:
        log.error("Knowledge Base validation FAILED with %d error(s):", len(all_errors))
        for err in all_errors:
            log.error("  x %s", err)
        return False

    log.info("Knowledge Base validation PASSED successfully (with %d warning(s)).", len(all_warnings))
    return True


if __name__ == "__main__":
    success = validate_kb()
    sys.exit(0 if success else 1)

