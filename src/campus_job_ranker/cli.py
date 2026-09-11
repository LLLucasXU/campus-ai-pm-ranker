from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import ValidationError, load_run_input
from .reporting import OUTPUT_DISPLAY_NAMES, generate_outputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campus-job-ranker",
        description="Rank campus jobs within one company and emit auditable artifacts.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Structured run input JSON")
    parser.add_argument("--output", required=True, type=Path, help="Output directory")
    return parser


def main(argv: list = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        run_input = load_run_input(payload)
        generated = generate_outputs(run_input, args.output)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    for filename, path in generated.items():
        print(f"已生成{OUTPUT_DISPLAY_NAMES.get(filename, '输出文件')}：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
