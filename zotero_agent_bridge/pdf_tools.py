from __future__ import annotations

import subprocess
from pathlib import Path

from pypdf import PdfReader

from .utils import extract_doi


def extract_pdf_text(path: Path, max_pages: int = 2) -> str:
    command = [
        "pdftotext",
        "-f",
        "1",
        "-l",
        str(max_pages),
        "-layout",
        "-nopgbrk",
        str(path),
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode == 0:
        text = completed.stdout.strip()
        if text:
            return text

    try:
        reader = PdfReader(path)
        return "\n\n".join(
            text
            for page in reader.pages[:max_pages]
            if (text := (page.extract_text() or "").strip())
        ).strip()
    except Exception:
        return ""


def guess_title_from_text(text: str) -> str | None:
    for line in (chunk.strip() for chunk in text.splitlines()):
        if len(line) < 12:
            continue
        if line.lower().startswith("doi"):
            continue
        return line
    return None


def extract_pdf_metadata(path: Path) -> dict[str, str]:
    text = extract_pdf_text(path)
    title = guess_title_from_text(text) or path.stem.replace("_", " ").replace("-", " ")
    doi = extract_doi(text) or extract_doi(path.stem)
    metadata: dict[str, str] = {"title": title}
    if doi:
        metadata["doi"] = doi
    return metadata
