from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
        tmp.write(content)
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
        handle.write("\n")


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value, flags=re.UNICODE).strip("-")
    return value or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = doi.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    match = DOI_PATTERN.search(value)
    return match.group(1).rstrip(").,;") if match else None


def extract_doi(text: str | None) -> str | None:
    if not text:
        return None
    match = DOI_PATTERN.search(text)
    return normalize_doi(match.group(1)) if match else None


def file_uri_to_path(uri: str | None) -> str | None:
    if not uri or not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    return unquote(parsed.path.lstrip("/")).replace("/", "\\")


def html_to_markdownish(value: str | None) -> str:
    if not value:
        return ""
    text = value
    replacements = [
        (r"<br\s*/?>", "\n"),
        (r"</p>", "\n\n"),
        (r"<p[^>]*>", ""),
        (r"<h1[^>]*>", "# "),
        (r"</h1>", "\n\n"),
        (r"<h2[^>]*>", "## "),
        (r"</h2>", "\n\n"),
        (r"<h3[^>]*>", "### "),
        (r"</h3>", "\n\n"),
        (r"<li[^>]*>", "- "),
        (r"</li>", "\n"),
        (r"</div>", "\n"),
        (r"<div[^>]*>", ""),
        (r"<blockquote[^>]*>", "> "),
        (r"</blockquote>", "\n\n"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(value: str | None) -> str:
    return html_to_markdownish(value).replace("\n", " ").strip()
