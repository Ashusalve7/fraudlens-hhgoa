"""Build normalized FraudLens graph load frames and local retrieval artifacts.

Inputs are read from the sponsor ``HHGOA_IEEE`` directory.  The script never
contacts TigerGraph.  It writes only load artifacts under ``pipeline/out`` and
produces a manifest that the loader uses for resumable, verifiable upserts.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT.parent / "HHGOA_IEEE"
OUT = HERE / "out"
LOAD = OUT / "load"
LOAD.mkdir(parents=True, exist_ok=True)

try:  # Works both as ``python pipeline/build_load_files.py`` and as a package.
    from .embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_many
    from .load_contract import (
        MANIFEST_PATH,
        atomic_write_json,
        inspect_sources,
        source_manifest,
    )
except ImportError:  # pragma: no cover - script execution path
    from embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_many
    from load_contract import MANIFEST_PATH, atomic_write_json, inspect_sources, source_manifest

TXN_KEEP = [
    "TransactionID", "ts", "TransactionAmt", "ProductCD", "channel", "risk_score",
    "card1", "card2", "card3", "card5", "addr1", "addr2", "dist1", "dist2",
    "P_emaildomain", "R_emaildomain",
] + [f"M{i}" for i in range(1, 10)] + [f"C{i}" for i in range(1, 15)] + [f"D{i}" for i in range(1, 16)]
IDENT_KEEP = ["TransactionID", "id_15", "id_23", "DeviceType", "DeviceInfo", "id_30", "id_31", "id_33"]
MISSING = "_NA_"


def na(values: pd.Series) -> pd.Series:
    text = values.astype("string")
    return text.isna() | text.isin(["", "nan", "None", "<NA>"])


def clean_str(values: pd.Series) -> pd.Series:
    return values.astype("string").where(~na(values), "").astype(str)


def _compact_flags(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Serialize nonempty source counters without a per-cell Python apply."""
    values = frame[columns].astype("string").fillna("")
    invalid = values.isin(["", "nan", "None", "<NA>", "_NA_"])
    result: list[str] = []
    for row, masks in zip(
        values.itertuples(index=False, name=None),
        invalid.itertuples(index=False, name=None),
        strict=True,
    ):
        result.append(
            "|".join(
                f"{column}={value}"
                for column, value, keep in zip(columns, row, masks, strict=True)
                if keep
            )
        )
    return pd.Series(result, index=frame.index, dtype="string")


def _profile_component(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "_na_"} else text


def device_profile_id(device_info: object, os_: object, browser: object, screen: object) -> str:
    """Return a stable device ID, excluding wholly unknown profiles.

    The four profile fields form the identity.  Treating four missing fields as
    a real profile would connect every unidentified transaction through one
    synthetic ``DP-*`` vertex.  Partially observed profiles remain valid.
    """
    components = (
        _profile_component(device_info),
        _profile_component(os_),
        _profile_component(browser),
        _profile_component(screen),
    )
    if not any(components):
        return ""
    # Keep the established delimiter/encoding so valid IDs remain stable across
    # the unknown-profile fix.
    return "DP-" + hashlib.md5("|".join(components).encode()).hexdigest()[:12]


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def atomic_npz(path: Path, **arrays: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)


def _section(text: str, start: str, end: str | None = None) -> str:
    start_at = text.find(start)
    if start_at < 0:
        return ""
    body_start = start_at + len(start)
    end_at = text.find(end, body_start) if end else -1
    return text[body_start:end_at if end_at >= 0 else None].strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "section"


def _policy_chunks() -> pd.DataFrame:
    """Extract deterministic policy/pattern chunks from the sponsor README."""
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    chunks: list[dict[str, object]] = []

    pattern_body = _section(readme, "## The five known fraud patterns", "## Regulatory references")
    # The sponsor README keeps the description on the same line as the bold
    # pattern title (for example, ``**1. Card testing.** A stolen ...``).
    pattern_matches = list(re.finditer(r"\*\*(\d+)\.\s+([^*\n]+)\*\*\s*(.*?)(?=\n\*\*\d+\.|\Z)", pattern_body, re.S))
    for match in pattern_matches:
        number, title, body = match.groups()
        title = title.strip()
        body = body.strip()
        text = f"Pattern {number}: {title}\n{body}"
        chunks.append({
            "kind": "fraud_pattern",
            "title": f"Pattern {number}: {title}",
            "text": text,
            "source_section": "The five known fraud patterns",
            "source_anchor": f"pattern-{number}-{_slug(title)}",
            "policy_rule": "",
            "patterns": f"pattern_{number}",
        })

    policy_body = _section(readme, "# Fraud Policy", "# Answer Format")
    # Each numbered policy section is a useful retrieval unit.  Keep tables and
    # examples intact; split only unusually large prose blocks on paragraphs.
    sections = re.split(r"(?m)^###\s+", policy_body)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading, _, body = section.partition("\n")
        heading = heading.strip()
        body = body.strip()
        if not heading:
            continue
        units = [body] if len(body) <= 2200 else re.split(r"\n\s*\n", body)
        for index, unit in enumerate(units):
            unit = unit.strip()
            if not unit:
                continue
            rules = "|".join(sorted(set(re.findall(r"\bR(?:[1-9]|10)\b", unit))))
            chunks.append({
                "kind": "policy",
                "title": heading if len(units) == 1 else f"{heading} ({index + 1})",
                "text": f"{heading}\n{unit}",
                "source_section": "Fraud Policy",
                "source_anchor": f"policy-{_slug(heading)}" + (f"-{index + 1}" if len(units) > 1 else ""),
                "policy_rule": rules,
                "patterns": "",
            })

    # A small amount of surrounding guidance is useful when an investigation
    # has no exact pattern match, but it is kept distinct from formal policy.
    for heading, end in (("## Things to know", "## Rules"), ("## Rules", "## Suggested graph schema")):
        body = _section(readme, heading, end)
        if body:
            chunks.append({
                "kind": "guidance",
                "title": heading.lstrip("# "),
                "text": body,
                "source_section": heading.lstrip("# "),
                "source_anchor": _slug(heading),
                "policy_rule": "",
                "patterns": "",
            })

    if not chunks:
        raise RuntimeError("sponsor README did not yield policy/pattern chunks")
    result = pd.DataFrame(chunks)
    result["source_path"] = "HHGOA_IEEE/README.md"
    result["chunk_index"] = np.arange(len(result), dtype=np.int32)
    result["content_hash"] = [
        hashlib.sha256(str(text).encode("utf-8")).hexdigest()
        for text in result["text"].astype(str)
    ]
    result["chunk_id"] = [
        "PC-" + hashlib.sha256(
            f"{row.source_path}|{row.source_anchor}|{row.chunk_index}|{row.content_hash}".encode()
        ).hexdigest()[:24]
        for row in result.itertuples(index=False)
    ]
    if result["chunk_id"].duplicated().any():
        raise ValueError("policy chunk IDs are not unique")
    return result[[
        "chunk_id", "kind", "title", "text", "source_path", "source_section",
        "source_anchor", "chunk_index", "content_hash", "policy_rule", "patterns",
    ]]


def _read_identity() -> pd.DataFrame:
    identity = pd.read_csv(DATA / "identity.csv", usecols=IDENT_KEEP, low_memory=False)
    if identity["TransactionID"].duplicated().any():
        raise ValueError("identity.csv contains duplicate TransactionID values")
    identity["TransactionID"] = identity["TransactionID"].astype(str)
    for column in ("id_15", "id_23", "DeviceType", "DeviceInfo", "id_30", "id_31", "id_33"):
        identity[column] = clean_str(identity[column])
    identity["device_id"] = [
        device_profile_id(device_info, os_, browser, screen)
        for device_info, os_, browser, screen in zip(
            identity["DeviceInfo"], identity["id_30"], identity["id_31"], identity["id_33"], strict=True
        )
    ]
    return identity


def _read_transactions() -> pd.DataFrame:
    columns = list(dict.fromkeys(["TransactionID", "TransactionDT", "ts", "customer_id"] + TXN_KEEP))
    chunks: list[pd.DataFrame] = []
    with pv.open_csv(DATA / "transactions.csv") as reader:
        for batch in reader:
            chunks.append(batch.select(columns).to_pandas())
    if not chunks:
        raise RuntimeError("transactions.csv produced no batches")
    tx = pd.concat(chunks, ignore_index=True)
    if tx["TransactionID"].duplicated().any():
        raise ValueError("transactions.csv contains duplicate TransactionID values")
    tx["TransactionID"] = tx["TransactionID"].astype(str)
    tx["ts"] = pd.to_datetime(tx["ts"], errors="raise")
    return tx


def _validate_card_map(tcm: pd.DataFrame, tx: pd.DataFrame) -> None:
    required = {"TransactionID", "customer_id", "card_id", "card1", "card4", "card6"}
    missing = sorted(required - set(tcm.columns))
    if missing:
        raise ValueError(f"txn_card_map.parquet missing columns: {missing}")
    if tcm["TransactionID"].duplicated().any() or tcm["card_id"].isna().any():
        raise ValueError("txn_card_map.parquet is not one-to-one or contains null card IDs")
    if set(tcm["TransactionID"].astype(str)) != set(tx["TransactionID"].astype(str)):
        raise ValueError("txn_card_map does not cover exactly the transaction IDs")
    raw_customer = tx[["TransactionID", "customer_id"]].copy()
    check = raw_customer.merge(tcm[["TransactionID", "customer_id"]], on="TransactionID", suffixes=("_tx", "_map"))
    if not (check["customer_id_tx"].astype(str) == check["customer_id_map"].astype(str)).all():
        raise ValueError("card map customer_id disagrees with transactions.csv")


def _next_txn(tx: pd.DataFrame) -> pd.DataFrame:
    ordered = tx[["TransactionID", "card_id", "ts"]].rename(columns={"TransactionID": "txn_id"}).sort_values(
        ["card_id", "ts", "txn_id"], kind="stable"
    ).reset_index(drop=True)
    # Graph primary IDs are STRING.  Sorting before conversion keeps numeric and
    # nonnumeric source IDs deterministic; conversion also prevents pandas from
    # upcasting shifted IDs to float.
    ordered["txn_id"] = ordered["txn_id"].astype(str)
    ordered["next_id"] = ordered.groupby("card_id", sort=False)["txn_id"].shift(-1)
    ordered["next_ts"] = ordered.groupby("card_id", sort=False)["ts"].shift(-1)
    nxt = ordered.dropna(subset=["next_id", "next_ts"]).copy()
    gaps = (nxt["next_ts"] - nxt["ts"]).dt.total_seconds()
    if (gaps < 0).any() or (gaps % 1 != 0).any():
        raise ValueError("NEXT_TXN produced negative or fractional gap_seconds")
    nxt["next_id"] = nxt["next_id"].astype(str)
    nxt["gap_seconds"] = gaps.round().astype("int64")
    if (nxt["txn_id"] == nxt["next_id"]).any() or nxt["txn_id"].duplicated().any() or nxt["next_id"].duplicated().any():
        raise ValueError("NEXT_TXN is not a one-to-one chronological chain")
    return nxt[["txn_id", "next_id", "gap_seconds"]]


def _case_edges(
    cc: pd.DataFrame, tx: pd.DataFrame, known_cards: set[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tx = tx.copy()
    tx["TransactionID"] = tx["TransactionID"].astype(str)
    rows: list[tuple[str, str]] = []
    for case in cc.itertuples(index=False):
        for txn_id in str(getattr(case, "txn_ids", "") or "").split("|"):
            txn_id = txn_id.strip()
            if txn_id and txn_id.lower() not in {"nan", "none"}:
                rows.append((str(case.case_id), txn_id))
    case_txn = pd.DataFrame(rows, columns=["case_id", "txn_id"]).drop_duplicates()
    known_txns = set(tx["TransactionID"].astype(str))
    case_txn = case_txn[case_txn["txn_id"].isin(known_txns)].reset_index(drop=True)

    case_card = cc[["case_id", "card_id"]].copy()
    case_card["case_id"] = case_card["case_id"].astype(str)
    case_card["card_id"] = case_card["card_id"].astype(str)
    if not case_card["card_id"].isin(known_cards).all():
        raise ValueError("closed case references a card absent from the card map")

    conn_rows: list[tuple[str, str]] = []
    for case in cc.itertuples(index=False):
        for card_id in str(getattr(case, "connected_card_ids", "") or "").split("|"):
            card_id = card_id.strip()
            if card_id and card_id.lower() not in {"nan", "none"}:
                conn_rows.append((str(case.case_id), card_id))
    case_conn = pd.DataFrame(conn_rows, columns=["case_id", "card_id"]).drop_duplicates()
    unknown = set(case_conn["card_id"]) - known_cards
    if unknown:
        raise ValueError(f"CASE_CONN_CARD references {len(unknown)} unknown cards")

    devices = tx[["TransactionID", "device_id"]].copy()
    devices["device_id"] = devices["device_id"].fillna("").astype(str)
    devices = devices[~devices["device_id"].isin({"", MISSING})]
    case_device = case_txn.merge(
        devices.rename(columns={"TransactionID": "txn_id"}), on="txn_id", how="inner"
    )[["case_id", "device_id"]].drop_duplicates().reset_index(drop=True)
    return case_txn, case_card, case_conn, case_device


def main() -> int:
    print("reading identity and transactions...")
    identity = _read_identity()
    tx = _read_transactions()
    tcm_path = OUT / "txn_card_map.parquet"
    if not tcm_path.exists():
        raise FileNotFoundError("run pipeline/derive_card_ids_final.py before building load files")
    tcm = pd.read_parquet(tcm_path)
    _validate_card_map(tcm, tx)
    tx = tx.merge(
        tcm[["TransactionID", "customer_id", "card_id", "card1", "card4", "card6"]],
        on="TransactionID", how="left", suffixes=("", "_map"), validate="one_to_one",
    )
    if "customer_id_map" in tx:
        if not (tx["customer_id"].astype(str) == tx["customer_id_map"].astype(str)).all():
            raise ValueError("card map customer IDs disagree with transaction customer IDs")
        tx = tx.drop(columns=["customer_id_map"])
    tx["device_id"] = tx["TransactionID"].map(identity.set_index("TransactionID")["device_id"])

    for column in ("ProductCD", "channel", "addr1", "addr2", "P_emaildomain", "R_emaildomain"):
        tx[column] = clean_str(tx[column])
    for column in ("card1", "card2", "card3", "card5"):
        tx[column] = clean_str(tx[column])
    for column in ("card4", "card6"):
        tx[column] = clean_str(tx[column])
    tx["m_flags"] = _compact_flags(tx, [f"M{i}" for i in range(1, 10)])
    tx["c_counts"] = _compact_flags(tx, [f"C{i}" for i in range(1, 15)])
    tx["d_deltas"] = _compact_flags(tx, [f"D{i}" for i in range(1, 16)])
    tx = tx.merge(
        identity[["TransactionID", "id_15", "id_23", "DeviceType"]],
        on="TransactionID", how="left", validate="one_to_one",
    )
    for column in ("id_15", "id_23", "DeviceType"):
        tx[column] = clean_str(tx[column])

    v_txn = pd.DataFrame({
        "txn_id": tx["TransactionID"].astype(str),
        "ts": tx["ts"],
        "amount": pd.to_numeric(tx["TransactionAmt"], errors="coerce").fillna(0.0),
        "product_cd": tx["ProductCD"],
        "channel": tx["channel"],
        "risk_score": pd.to_numeric(tx["risk_score"], errors="coerce").fillna(0.0),
        "card1": tx["card1"], "card2": tx["card2"], "card3": tx["card3"], "card5": tx["card5"],
        "addr1": tx["addr1"], "addr2": tx["addr2"],
        "dist1": pd.to_numeric(tx["dist1"], errors="coerce").fillna(-1.0),
        "dist2": pd.to_numeric(tx["dist2"], errors="coerce").fillna(-1.0),
        "p_email": tx["P_emaildomain"], "r_email": tx["R_emaildomain"],
        "m_flags": tx["m_flags"], "c_counts": tx["c_counts"], "d_deltas": tx["d_deltas"],
        "id_15": tx["id_15"], "id_23": tx["id_23"], "device_type": tx["DeviceType"],
    })
    atomic_parquet(v_txn, LOAD / "v_Transaction.parquet")

    v_card = (
        tx.groupby("card_id", sort=False)
        .agg(first_ts=("ts", "min"), last_ts=("ts", "max"), n_txn=("ts", "size"),
             network=("card4", "first"), card_type=("card6", "first"))
        .reset_index()
    )
    v_card["n_txn"] = pd.to_numeric(v_card["n_txn"], errors="coerce").fillna(0).astype("int64")
    v_card["network"] = clean_str(v_card["network"])
    v_card["card_type"] = clean_str(v_card["card_type"])
    atomic_parquet(v_card, LOAD / "v_Card.parquet")

    cards_per_cust = tcm[["customer_id", "card_id"]].drop_duplicates()
    cust_stats = (
        tx.groupby("customer_id", sort=False)
        .agg(first_ts=("ts", "min"), last_ts=("ts", "max"), n_txn=("ts", "size"))
        .reset_index()
    )
    v_cust = cust_stats.merge(
        cards_per_cust.groupby("customer_id").size().rename("n_cards"), on="customer_id", how="left"
    )
    v_cust["n_cards"] = pd.to_numeric(v_cust["n_cards"], errors="coerce").fillna(0).astype("int64")
    v_cust["n_txn"] = pd.to_numeric(v_cust["n_txn"], errors="coerce").fillna(0).astype("int64")
    atomic_parquet(v_cust, LOAD / "v_Customer.parquet")

    known_device_mask = tx["device_id"].fillna("").astype(str).ne("")
    known_device_mask &= tx["device_id"].fillna("").astype(str).ne(MISSING)
    tx_device = tx[known_device_mask].copy()
    device_meta = (
        identity.groupby("device_id", sort=False)
        .agg(device_info=("DeviceInfo", "first"), os=("id_30", "first"),
             browser=("id_31", "first"), screen=("id_33", "first"),
             device_type=("DeviceType", "first"))
        .reset_index()
    )
    dev = (
        tx_device.groupby("device_id", sort=False)
        .agg(n_txn=("TransactionID", "size"), n_cards=("card_id", "nunique"))
        .reset_index()
    ).merge(device_meta, on="device_id", how="left")
    for column in ("device_info", "os", "browser", "screen", "device_type"):
        dev[column] = clean_str(dev[column])
    for column in ("n_txn", "n_cards", "n_fraud_cases"):
        if column not in dev:
            dev[column] = 0
        dev[column] = pd.to_numeric(dev[column], errors="coerce").fillna(0).astype("int64")

    print("writing static vertices and edges...")
    cc = pd.read_csv(DATA / "closed_cases_history.csv", low_memory=False)
    cc["case_id"] = cc["case_id"].astype(str)
    cc["customer_id"] = clean_str(cc["customer_id"])
    cc["card_id"] = clean_str(cc["card_id"])
    cc["report_bool"] = cc["report_filed"].astype(str).str.strip().str.lower().eq("yes")
    v_cc = pd.DataFrame({
        "case_id": cc["case_id"], "customer_id": cc["customer_id"], "card_id": cc["card_id"],
        "outcome": clean_str(cc["outcome"]), "pattern": clean_str(cc["pattern"]),
        "opened_at": pd.to_datetime(cc["opened_at"], errors="raise"),
        "closed_at": pd.to_datetime(cc["closed_at"], errors="raise"),
        "n_txns": pd.to_numeric(cc["n_txns"], errors="coerce").fillna(0).astype("int64"),
        "exposure_usd": pd.to_numeric(cc["exposure_usd"], errors="coerce").fillna(0.0),
        "report_filed": cc["report_bool"], "actions": clean_str(cc["actions_taken"]),
        "notes": clean_str(cc["analyst_notes"]),
    })
    atomic_parquet(v_cc, LOAD / "v_ClosedCase.parquet")

    emails = pd.concat([tx["P_emaildomain"], tx["R_emaildomain"]]).replace("", pd.NA).dropna().unique()
    free_domains = {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
        "live.com", "msn.com", "comcast.net", "verizon.net", "att.net", "sbcglobal.net",
        "me.com", "ymail.com", "gmail",
    }
    v_email = pd.DataFrame({"domain": pd.Series(emails, dtype="string").astype(str)})
    v_email["is_free"] = v_email["domain"].isin(free_domains)
    atomic_parquet(v_email, LOAD / "v_EmailDomain.parquet")

    regions = pd.Series(tx.loc[tx["addr1"] != "", "addr1"].unique(), dtype="string").astype(str)
    atomic_parquet(pd.DataFrame({"region_id": regions}), LOAD / "v_BillingRegion.parquet")

    e_own = cards_per_cust.merge(v_card[["card_id", "first_ts"]], on="card_id", how="left")
    e_own = e_own[["customer_id", "card_id", "first_ts"]].rename(columns={"first_ts": "first_seen"})
    atomic_parquet(e_own, LOAD / "e_OWNS_CARD.parquet")

    paid_with = tx[["TransactionID", "card_id"]].rename(columns={"TransactionID": "from"})
    paid_with["from"] = paid_with["from"].astype(str)
    atomic_parquet(paid_with, LOAD / "e_PAID_WITH.parquet")
    from_device = tx.loc[known_device_mask, ["TransactionID", "device_id"]].rename(columns={"TransactionID": "from"})
    from_device["from"] = from_device["from"].astype(str)
    atomic_parquet(from_device, LOAD / "e_FROM_DEVICE.parquet")
    p_email = tx.loc[tx["P_emaildomain"] != "", ["TransactionID", "P_emaildomain"]].rename(
        columns={"TransactionID": "from", "P_emaildomain": "domain"}
    )
    p_email["from"] = p_email["from"].astype(str)
    atomic_parquet(p_email, LOAD / "e_P_EMAIL.parquet")
    r_email = tx.loc[tx["R_emaildomain"] != "", ["TransactionID", "R_emaildomain"]].rename(
        columns={"TransactionID": "from", "R_emaildomain": "domain"}
    )
    r_email["from"] = r_email["from"].astype(str)
    atomic_parquet(r_email, LOAD / "e_R_EMAIL.parquet")
    billed_in = tx.loc[tx["addr1"] != "", ["TransactionID", "addr1"]].rename(
        columns={"TransactionID": "from", "addr1": "region_id"}
    )
    billed_in["from"] = billed_in["from"].astype(str)
    atomic_parquet(billed_in, LOAD / "e_BILLED_IN.parquet")
    atomic_parquet(_next_txn(tx), LOAD / "e_NEXT_TXN.parquet")

    known_cards = set(v_card["card_id"].astype(str))
    case_txn, case_card, case_conn, case_device = _case_edges(cc, tx, known_cards)
    atomic_parquet(case_txn, LOAD / "e_CASE_TXN.parquet")
    atomic_parquet(case_card, LOAD / "e_CASE_CARD.parquet")
    atomic_parquet(case_conn, LOAD / "e_CASE_CONN_CARD.parquet")
    atomic_parquet(case_device, LOAD / "e_CASE_DEVICE.parquet")

    # Count only confirmed cases when enriching a device profile.
    confirmed_devices = (
        case_device.merge(cc[["case_id", "outcome"]], on="case_id", how="left")
        .query("outcome == 'confirmed_fraud'")[["device_id"]]
        .drop_duplicates()
    )
    fraud_counts = confirmed_devices.groupby("device_id").size()
    dev["n_fraud_cases"] = dev["device_id"].map(fraud_counts).fillna(0).astype("int64")
    atomic_parquet(dev, LOAD / "v_DeviceProfile.parquet")

    policy = _policy_chunks()
    # The graph schema intentionally remains compatible with the existing
    # PolicyChunk vertex.  Rich provenance stays in the local artifact and can
    # be joined by chunk_id without requiring a remote schema migration.
    atomic_parquet(policy[["chunk_id", "kind", "title", "text"]], LOAD / "v_PolicyChunk.parquet")
    atomic_parquet(policy, OUT / "policy_chunks.parquet")
    vectors = embed_many(policy["text"].astype(str).tolist())
    atomic_npz(
        OUT / "policy_embeddings.npz",
        chunk_ids=np.asarray(policy["chunk_id"].tolist(), dtype=str),
        vectors=vectors,
        model=np.asarray([EMBEDDING_MODEL]),
        dimension=np.asarray([EMBEDDING_DIM], dtype=np.int32),
    )
    atomic_write_json(OUT / "policy_manifest.json", {
        "model": EMBEDDING_MODEL,
        "dimension": EMBEDDING_DIM,
        "count": int(len(policy)),
        "source": "HHGOA_IEEE/README.md",
        "chunks": [
            {"chunk_id": row.chunk_id, "kind": row.kind, "source_anchor": row.source_anchor,
             "policy_rule": row.policy_rule, "patterns": row.patterns}
            for row in policy.itertuples(index=False)
        ],
    })

    source_inputs = [
        DATA / "transactions.csv", DATA / "identity.csv", DATA / "closed_cases_history.csv",
        OUT / "txn_card_map.parquet", OUT / "card_map.parquet", OUT / "card_rule_report.json",
    ]
    validation = inspect_sources(deep=True)
    manifest = source_manifest(source_files=source_inputs, validation=validation)
    manifest["builder"] = {
        "version": "fraudlens-builder/v2",
        "policy_source": "HHGOA_IEEE/README.md",
        "case_device_rule": "direct ClosedCase.txn_ids -> observed DeviceProfile only",
        "unknown_device_rule": "exclude profiles with no DeviceInfo/OS/browser/screen evidence",
        "next_txn_rule": "stable per-card ts/TransactionID chain; STRING IDs; integer non-negative gap",
    }
    atomic_write_json(MANIFEST_PATH, manifest)
    if not validation["valid"]:
        raise RuntimeError("load source validation failed: " + "; ".join(validation["errors"]))

    print("\n=== load frames ===")
    for path in sorted(LOAD.glob("*.parquet")):
        print(f"  {path.name:28s} {len(pd.read_parquet(path)):>9,} rows")
    print(f"manifest: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
