#!/usr/bin/env python3
"""Package a safe submission archive from tracked/allow-listed project files."""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "load",
    "HHGOA_IEEE",
}
EXCLUDED_NAMES = {".env"}
EXCLUDED_SUFFIXES = {".pyc", ".log", ".parquet"}


def git_files() -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    files = [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    return files or None


def fallback_files() -> list[Path]:
    allowed_roots = {"fraudlens", "docs", "scripts", ".github"}
    allowed_root_files = {
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        "Makefile",
        "pyproject.toml",
    }
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts[0] not in allowed_roots and rel.as_posix() not in allowed_root_files:
            continue
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "dist" / "fraudlens-submission.zip")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    scan = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "secret_scan.py")], cwd=ROOT, check=False
    )
    if scan.returncode:
        print("Refusing to package: secret scan failed.", file=sys.stderr)
        return scan.returncode

    files = git_files()
    source = "git tracked files" if files is not None else "allow-listed fallback files"
    files = files if files is not None else fallback_files()
    if not files:
        print("No files selected for package.", file=sys.stderr)
        return 1

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(set(files)):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if rel.parts[0] == "dist" or any(part in EXCLUDED_PARTS for part in rel.parts):
                continue
            if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            archive.write(path, rel.as_posix())
    print(f"Packaged {len(files)} selected paths from {source}: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
