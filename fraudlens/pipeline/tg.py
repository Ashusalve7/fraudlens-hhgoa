"""Shared TigerGraph connection helper for the FraudLens pipeline.

Reads TG_HOST / TG_SECRET from environment or a .env at the repo root.
Exposes `get_conn()` returning a connected pyTigerGraph TigerGraphConnection.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TG_HOST = os.environ.get("TG_HOST", "").rstrip("/")
TG_SECRET = os.environ.get("TG_SECRET", "")
GRAPHNAME = os.environ.get("TG_GRAPHNAME", "FraudGraph")


def get_conn(graphname: str | None = None):
    import pyTigerGraph as tg

    if not TG_HOST or not TG_SECRET:
        raise RuntimeError("TG_HOST and TG_SECRET must be set in the environment or .env")

    conn = tg.TigerGraphConnection(host=TG_HOST, graphname=graphname or GRAPHNAME, gsqlSecret=TG_SECRET)
    return conn


if __name__ == "__main__":
    conn = get_conn()
    print("host:", TG_HOST)
    try:
        print("echo:", conn.echo())
        print("version:", conn.getVer())
    except Exception as e:
        print("basic probe failed:", e)
        sys.exit(1)
    try:
        gs = conn.gsql("ls", dialect="gsql")
        print("gsql ls (first 800 chars):")
        print(str(gs)[:800])
    except Exception as e:
        print("gsql ls failed:", type(e).__name__, str(e)[:300])
