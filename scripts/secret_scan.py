#!/usr/bin/env python3
"""Fail CI when an obvious credential is committed.

The scanner deliberately prints only file/line locations and rule names—never
matched secret values.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "load",
    "HHGOA_IEEE",
}
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".env",
    ".example",
    ".gql",
    ".gsql",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    "openai-key": re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "bearer-token": re.compile(r"(?i)\bauthorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._-]{20,}"),
    "hardcoded-tg-secret": re.compile(
        r"(?i)TG_SECRET\s*=\s*(?:os\.(?:environ\.get|getenv)\([^,]+,\s*)?['\"](?!<)[^'\"]{12,}['\"]"
    ),
    "generic-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"
    ),
}
ALLOWLIST = {
    "fraudlens/.env.example",
    "SECURITY.md",
}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".env", "Dockerfile"}:
            continue
        yield path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    findings: list[tuple[str, int, str]] = []
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in RULES.items():
                if pattern.search(line):
                    findings.append((rel, lineno, name))
    if findings:
        print("Potential committed secrets detected (values redacted):")
        for rel, lineno, name in findings:
            print(f"- {rel}:{lineno}: {name}")
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
