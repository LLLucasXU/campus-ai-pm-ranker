#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from campus_job_ranker.profile import find_resume_candidates, is_supported_resume_source  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a user-specified resume path without guessing.")
    parser.add_argument("--resume", type=Path, help="Resume path explicitly provided by the user")
    parser.add_argument(
        "--root",
        type=Path,
        help="Compatibility-only fallback for listing candidates; do not use it to select a resume automatically.",
    )
    args = parser.parse_args()
    if args.resume is not None:
        candidate = args.resume.expanduser().absolute()
        candidates = [candidate] if is_supported_resume_source(candidate) else []
    elif args.root is not None:
        candidates = find_resume_candidates(args.root)
    else:
        candidates = []
    print(
        json.dumps(
            {
                "status": "ok" if len(candidates) == 1 else "missing" if not candidates else "ambiguous",
                "candidates": [str(path) for path in candidates],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if len(candidates) == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
