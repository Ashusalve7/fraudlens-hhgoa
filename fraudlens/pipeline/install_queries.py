"""Install the evidence and graph-tool GSQL queries.

Queries are parsed by CREATE QUERY boundaries rather than by a fragile line
split, and graph-name selection follows TG_GRAPHNAME.  Existing queries are
dropped only by their exact names; unrelated graph objects are untouched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tg import GRAPHNAME, get_conn  # noqa: E402

QFILE = HERE.parent / "gsql" / "evidence_queries.gsql"


def _queries(raw: str) -> list[tuple[str, str]]:
    text = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("--"))
    matches = list(re.finditer(r"(?m)^CREATE\s+QUERY\s+(\w+)", text, flags=re.I))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        statement = text[match.start():end].strip().rstrip(";").strip()
        result.append((match.group(1), statement))
    return result


def _is_error(value: object) -> bool:
    return "error" in str(value).lower()


def main() -> int:
    conn = get_conn()
    queries = _queries(QFILE.read_text(encoding="utf-8"))
    if not queries:
        print("no CREATE QUERY statements found")
        return 1
    print(f"{len(queries)} queries: {[name for name, _ in queries]}")
    for name, query in queries:
        try:
            conn.gsql(f"USE GRAPH {GRAPHNAME}\nDROP QUERY {name}")
        except Exception:
            pass
        try:
            output = conn.gsql(f"USE GRAPH {GRAPHNAME}\n{query}")
        except Exception as exc:
            print(f"FAILED create {name}: {str(exc)[:500]}")
            return 1
        if _is_error(output):
            print(f"FAILED create {name}: {str(output)[:500]}")
            return 1
        print(f"created {name}: OK")

    try:
        output = conn.gsql(f"USE GRAPH {GRAPHNAME}\nINSTALL QUERY ALL")
    except Exception as exc:
        print(f"FAILED install: {str(exc)[:500]}")
        return 1
    if _is_error(output) or "no query" in str(output).lower():
        print(f"FAILED install: {str(output)[:500]}")
        return 1
    print("install: OK |", str(output)[:300].replace("\n", " | "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
