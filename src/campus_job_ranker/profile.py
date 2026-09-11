from __future__ import annotations

from pathlib import Path
from typing import List


EXCLUDED_DIRECTORY_NAMES = frozenset({"tmp", "runs", "docs", ".agents"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


def _is_excluded(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts[:-1]
    return any(
        part in EXCLUDED_DIRECTORY_NAMES or part.startswith(".")
        for part in relative_parts
    )


def is_supported_resume_source(path: Path) -> bool:
    """Return whether an explicitly supplied resume has a supported document format."""

    return path.is_file() and path.suffix.lower() in DOCUMENT_EXTENSIONS


def find_resume_candidates(root: Path) -> List[Path]:
    """Find plausible resume sources without guessing between duplicates."""

    resolved_root = root.expanduser().absolute()
    documents: List[Path] = []
    images: List[Path] = []
    for path in resolved_root.rglob("*"):
        if not path.is_file() or _is_excluded(path, resolved_root):
            continue
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_EXTENSIONS:
            documents.append(path)
        elif suffix in IMAGE_EXTENSIONS:
            images.append(path)
    return sorted(documents) if documents else sorted(images)
