#!/usr/bin/env python3
"""Create a deterministic release manifest for code, model, answers, and data."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_PATTERNS = (
    "fraudlens/runner.py",
    "fraudlens/validator.py",
    "fraudlens/agent/**/*.py",
    "fraudlens/eval/**/*.py",
    "fraudlens/pipeline/**/*.py",
    "fraudlens/gsql/*.gsql",
    "fraudlens/mcp/**/*.py",
    "render.yaml",
    "wrangler.toml",
    "fraudlens/dashboard/app.py",
    "fraudlens/dashboard/src/**/*",
    "fraudlens/dashboard/public/**/*",
    "fraudlens/dashboard/dist/**/*",
    "fraudlens/pyproject.toml",
    "fraudlens/uv.lock",
    "fraudlens/dashboard/package.json",
    "fraudlens/dashboard/package-lock.json",
    "fraudlens/schemas/*.json",
)
DATA_FILES = (
    "HHGOA_IEEE/transactions.csv",
    "HHGOA_IEEE/identity.csv",
    "HHGOA_IEEE/closed_cases_history.csv",
    "HHGOA_IEEE/case_pack.csv",
)
ANSWER_FILES = tuple(f"fraudlens/cases/HHG-{i:03d}.json" for i in range(1, 21))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand(pattern: str) -> list[Path]:
    return [p for p in ROOT.glob(pattern) if p.is_file()]


def file_record(path: Path, hash_data: bool) -> dict[str, object]:
    record: dict[str, object] = {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
    }
    if hash_data or "cases" in path.parts or path.suffix in {".py", ".gsql", ".toml", ".lock", ".json", ".txt", ".jsx", ".js", ".css", ".html"}:
        record["sha256"] = sha256(path)
    return record


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release_manifest.json")
    parser.add_argument("--hash-data", action="store_true", help="Hash the large sponsor CSV files")
    parser.add_argument("--strict", action="store_true", help="Fail when any expected artifact is missing")
    args = parser.parse_args()

    paths: dict[str, Path] = {}
    for pattern in CODE_PATTERNS:
        paths.update({str(path): path for path in expand(pattern)})
    for rel in DATA_FILES:
        path = ROOT / rel
        if path.is_file():
            paths[str(path)] = path
    for rel in ANSWER_FILES:
        path = ROOT / rel
        if path.is_file():
            paths[str(path)] = path
    for rel in (
        "fraudlens/eval/out/model.json",
        "fraudlens/eval/out/eval_report.txt",
        "fraudlens/pipeline/out/graph_health.json",
        "fraudlens/pipeline/out/gds_check.json",
        "fraudlens/pipeline/out/gds_degree_centrality.json",
    ):
        path = ROOT / rel
        if path.is_file():
            paths[str(path)] = path

    expected_missing = [rel for rel in (*ANSWER_FILES, *DATA_FILES) if not (ROOT / rel).is_file()]
    if args.strict and expected_missing:
        print("Missing required release artifacts:")
        for rel in expected_missing:
            print(f"- {rel}")
        return 1

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "files": [file_record(path, args.hash_data) for path in sorted(paths.values(), key=lambda p: p.as_posix())],
        "missing_expected": expected_missing,
    }
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
