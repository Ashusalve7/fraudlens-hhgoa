"""Apply the FraudLens schema in an idempotent, inspectable order.

The script is deliberately a schema utility only; it never loads data.  It
understands the optional global vector job in ``gsql/schema.gsql`` separately
from ordinary CREATE statements so a partially applied schema can be retried.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tg import GRAPHNAME, get_conn  # noqa: E402

SCHEMA = HERE.parent / "gsql" / "schema.gsql"


def _without_comment_lines(raw: str) -> str:
    return "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("--"))


def _is_already_exists(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("already exists", "already defined", "used by another object", "duplicate"))


def _execute(conn: object, statement: str, *, allow_exists: bool = True) -> bool:
    label = " ".join(statement.split()[:4])[:100]
    try:
        output = conn.gsql(statement)  # type: ignore[attr-defined]
        rendered = str(output)
        if "error" in rendered.lower():
            if allow_exists and _is_already_exists(rendered):
                print(f"SKIP (exists): {label}")
                return True
            print(f"FAIL: {label}\n{rendered[:500]}")
            return False
        print(f"OK: {label}")
        return True
    except Exception as exc:
        message = str(exc)
        if allow_exists and _is_already_exists(message):
            print(f"SKIP (exists): {label}")
            return True
        print(f"FAIL: {label}\n{message[:500]}")
        return False


def _schema_parts(raw: str) -> tuple[list[str], str | None, str | None]:
    """Return ordinary CREATE statements and the optional vector job/run."""
    job_match = re.search(
        r"CREATE\s+GLOBAL\s+SCHEMA_CHANGE\s+JOB\s+(\w+)\s*\{(?P<body>.*?)\}\s*"
        r"RUN\s+GLOBAL\s+SCHEMA_CHANGE\s+JOB\s+\w+\s*;?",
        raw,
        flags=re.I | re.S,
    )
    job_name = None
    job_run = None
    if job_match:
        job_name = job_match.group(1)
        body = job_match.group("body").strip()
        raw = raw[:job_match.start()] + "\n" + raw[job_match.end():]
        # Keep the job body as its own statement.  ALTER VERTEX is valid in a
        # global schema-change job and is not sent as a graph query.
        job_run = body
    statements = [
        part.strip().rstrip(";").strip()
        for part in re.split(r"(?m)(?=^CREATE\s+)", raw, flags=re.I)
        if part.strip()
    ]
    return statements, job_name, job_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-jobs", action="store_true", help="do not apply vector attributes")
    args = parser.parse_args()
    raw = _without_comment_lines(SCHEMA.read_text(encoding="utf-8"))
    statements, job_name, job_body = _schema_parts(raw)
    conn = get_conn()
    if job_body and not args.skip_jobs:
        # CREATE JOB is separate from RUN so both operations can be retried.
        job_create = f"CREATE GLOBAL SCHEMA_CHANGE JOB {job_name} {{\n{job_body}\n}}"
        if not _execute(conn, job_create):
            return 1
        if not _execute(conn, f"RUN GLOBAL SCHEMA_CHANGE JOB {job_name}"):
            return 1
    elif job_body:
        print("skipping global vector schema job")

    for index, statement in enumerate(statements, 1):
        # The graph name is kept in the checked-in schema for compatibility;
        # do not silently create a second graph when an override is supplied.
        print(f"[{index}/{len(statements)}] {' '.join(statement.split()[:5])[:100]}")
        if not _execute(conn, statement):
            return 1
    print(f"schema ready: graph={GRAPHNAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
