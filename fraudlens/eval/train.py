"""Train and evaluate the production FraudLens calibrator and pattern rules.

The pattern score in the artifact is computed by calling the exact
``agent.decision.detect_pattern`` function used at inference time.  No pattern
accuracy constant is copied from an older evaluator.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from agent.decision import EXAM_PRIOR, MODEL_FEATURE_COUNT, detect_pattern

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FEATURES = [
    "flagged_amount", "flagged_online", "flagged_risk", "n_small_auth_1h",
    "amt_ratio_30d", "product_new", "new_dev_share_24h", "proxy_share_24h",
    "device_shared_cards_7d", "region_new", "region_new_n_72h", "home_active_72h",
    "online_share_shift", "pemail_changed", "m1_not_T", "n_txn_24h",
]
PATTERNS = [
    "card_testing", "card_not_present_fraud", "card_not_present_new_device",
    "out_of_region_use", "account_takeover", "undocumented", "none",
]


def platt(scores: Iterable[float], y: Iterable[int], lo: float = 1e-6):
    """Fit a one-dimensional sigmoid, including a safe one-class fallback."""
    raw = np.asarray(list(scores), dtype=float)
    target = np.asarray(list(y), dtype=int)
    if len(raw) == 0:
        return (lambda x: np.full(np.asarray(x).shape, 0.5), None, 0.0, 1.0)
    raw = np.nan_to_num(raw, nan=0.0, posinf=50.0, neginf=-50.0)
    low, high = np.percentile(raw, [1, 99])
    if not math.isfinite(float(low)) or not math.isfinite(float(high)) or low == high:
        low, high = float(raw.min()), float(raw.max())
    if low == high:
        high = low + 1.0
    clipped = np.clip(raw, low, high)
    mean, std = float(clipped.mean()), float(clipped.std())
    std = std if std > 1e-9 else 1.0
    z = ((clipped - mean) / std).reshape(-1, 1)
    if len(np.unique(target)) < 2:
        prior = float(target.mean()) if len(target) else 0.5
        model = None
        w, b = 0.0, math.log(max(prior, 1e-6) / max(1 - prior, 1e-6))

        def constant(values):
            return np.full(np.asarray(values).shape, prior, dtype=float)

        return constant, model, mean, std
    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(z, target)
    w = float(model.coef_[0][0])
    b = float(model.intercept_[0])

    def calibrate(values):
        arr = np.asarray(values, dtype=float)
        arr = np.nan_to_num(arr, nan=0.0, posinf=50.0, neginf=-50.0)
        zz = (np.clip(arr, low, high) - mean) / std
        return 1.0 / (1.0 + np.exp(-np.clip(w * zz + b, -700, 700)))

    return calibrate, model, mean, std


def _safe_auc(y: Iterable[int], p: Iterable[float]) -> float:
    y = np.asarray(list(y), dtype=int)
    p = np.asarray(list(p), dtype=float)
    if len(y) == 0 or len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))


def _safe_brier(y: Iterable[int], p: Iterable[float]) -> float:
    y = np.asarray(list(y), dtype=int)
    p = np.asarray(list(p), dtype=float)
    return float(brier_score_loss(y, p)) if len(y) else float("nan")


def _shift_probability(p: np.ndarray, train_prior: float, exam_prior: float = EXAM_PRIOR, temperature: float = 1.5) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    logit = np.log(p / (1 - p)) / max(float(temperature), 1e-9)
    logit += math.log(exam_prior / (1 - exam_prior)) - math.log(train_prior / (1 - train_prior))
    return 1.0 / (1.0 + np.exp(-np.clip(logit, -700, 700)))


def evaluate_pattern_detector(frame: pd.DataFrame) -> dict[str, Any]:
    """Evaluate the exact production detector on a labeled feature table."""
    if frame.empty:
        return {"n": 0, "accuracy": float("nan"), "confusion_matrix": {}, "per_class": {}}
    predicted: list[str] = []
    truth: list[str] = []
    for _, row in frame.iterrows():
        # The feature row also carries detector extras.  Passing it as the
        # episode context mirrors runner._detector_context without consulting
        # the precomputed predicted_pattern column.
        features = {key: row.get(key) for key in frame.columns}
        pattern, _ = detect_pattern(features, features)
        predicted.append(pattern)
        truth.append(str(row.get("pattern", "none")))
    labels = sorted(set(PATTERNS) | set(truth) | set(predicted))
    matrix: dict[str, dict[str, int]] = {actual: {pred: 0 for pred in labels} for actual in labels}
    per_class: dict[str, dict[str, float | int]] = {}
    for actual, predicted_value in zip(truth, predicted):
        matrix.setdefault(actual, {label: 0 for label in labels})[predicted_value] = matrix.setdefault(actual, {}).get(predicted_value, 0) + 1
    for actual in labels:
        support = sum(matrix.get(actual, {}).values())
        correct = matrix.get(actual, {}).get(actual, 0)
        per_class[actual] = {"support": support, "recall": correct / support if support else float("nan")}
    correct = sum(a == b for a, b in zip(truth, predicted))
    cleared = frame["outcome"].astype(str).str.lower().eq("cleared") if "outcome" in frame else pd.Series(False, index=frame.index)
    none_correct = sum(a == "none" and b == "none" for a, b in zip(truth, predicted) if cleared.iloc[len([x for x in []])]) if False else None
    # Compute legitimate-class accuracy without relying on row ordering tricks.
    legit_rows = [i for i, outcome in enumerate(frame["outcome"].astype(str)) if outcome.lower() == "cleared"] if "outcome" in frame else []
    legit_accuracy = (
        sum(truth[i] == predicted[i] == "none" for i in legit_rows) / len(legit_rows)
        if legit_rows else float("nan")
    )
    return {
        "n": len(truth),
        "accuracy": correct / len(truth),
        "confusion_matrix": matrix,
        "per_class": per_class,
        "cleared_none_accuracy": legit_accuracy,
    }


def _reliability(y: np.ndarray, p: np.ndarray, bins: int = 8) -> list[dict[str, float | int]]:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    result: list[dict[str, float | int]] = []
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (p >= left) & (p < right if right < 1.0 else p <= right)
        if not mask.any():
            continue
        result.append({
            "lower": float(left),
            "upper": float(right),
            "n": int(mask.sum()),
            "mean_probability": float(p[mask].mean()),
            "observed_rate": float(y[mask].mean()),
        })
    return result


def fit_model(frame: pd.DataFrame) -> tuple[dict[str, Any], str]:
    """Fit a time-safe model and return ``(artifact, report)``."""
    if frame.empty:
        raise ValueError("cannot train on an empty feature table")
    frame = frame.sort_values("opened_at").reset_index(drop=True)
    frame["y"] = (frame["outcome"].astype(str) == "confirmed_fraud").astype(int)
    X = frame[FEATURES].astype(float).fillna(0.0)
    split = max(1, int(len(frame) * 0.75))
    split = min(split, len(frame) - 1) if len(frame) > 1 else split
    train_idx, test_idx = frame.index[:split], frame.index[split:]
    scaler = StandardScaler().fit(X.loc[train_idx])
    X_train = scaler.transform(X.loc[train_idx])
    X_test = scaler.transform(X.loc[test_idx])
    y_train = frame.loc[train_idx, "y"].to_numpy()
    y_test = frame.loc[test_idx, "y"].to_numpy()
    if len(np.unique(y_train)) < 2:
        lr = None
        raw_train = np.zeros(len(train_idx), dtype=float)
        raw_test = np.zeros(len(test_idx), dtype=float)
        coef = np.zeros(len(FEATURES), dtype=float)
        intercept = 0.0
    else:
        lr = LogisticRegression(max_iter=2000, C=0.5)
        lr.fit(X_train, y_train)
        raw_train = lr.decision_function(X_train)
        raw_test = lr.decision_function(X_test)
        coef = lr.coef_[0]
        intercept = float(lr.intercept_[0])
    platt_fn, platt_model, platt_mean, platt_std = platt(raw_train, y_train)
    p_train_platt = np.asarray(platt_fn(raw_train), dtype=float)
    p_test_platt = np.asarray(platt_fn(raw_test), dtype=float)
    train_prior = float(frame.loc[train_idx, "y"].mean())
    if not 0 < train_prior < 1:
        train_prior = float(frame["y"].mean())
    exam_prior = EXAM_PRIOR
    p_test_final = _shift_probability(p_test_platt, train_prior, exam_prior, 1.5)
    auc = _safe_auc(y_test, p_test_platt)
    brier = _safe_brier(y_test, p_test_platt)
    final_brier = _safe_brier(y_test, p_test_final)

    pattern_eval = evaluate_pattern_detector(frame)
    # Customer-disjoint evaluation is diagnostic only; never use a customer's
    # holdout rows to fit the production artifact.
    customer_auc = float("nan")
    if "customer_id" in frame and frame["customer_id"].nunique() > 1:
        customers = frame["customer_id"].astype(str)
        train_customers = set(customers.loc[train_idx])
        disjoint_test = frame.index[~customers.isin(train_customers)]
        if len(disjoint_test):
            disjoint_raw = np.zeros(len(disjoint_test), dtype=float)
            if lr is not None:
                disjoint_raw = lr.decision_function(scaler.transform(X.loc[disjoint_test]))
            disjoint_p = np.asarray(platt_fn(disjoint_raw), dtype=float)
            customer_auc = _safe_auc(frame.loc[disjoint_test, "y"], disjoint_p)

    artifact: dict[str, Any] = {
        "features": FEATURES,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coef": coef.tolist(),
        "intercept": intercept,
        "platt": {"mean": platt_mean, "std": platt_std, "w": float(getattr(platt_model, "coef_", np.array([[0.0]]))[0][0]) if platt_model is not None else 0.0, "b": float(getattr(platt_model, "intercept_", np.array([0.0]))[0]) if platt_model is not None else 0.0},
        "train_base_rate": train_prior,
        "exam_base_rate": exam_prior,
        "temperature": 1.5,
        "response_likelihood": {"denied": 8.0, "confirmed": 0.125, "no_response": 1.0},
        "holdout_auc": auc,
        "holdout_brier": brier,
        "post_shift_holdout_brier": final_brier,
        "customer_disjoint_auc": customer_auc,
        "reliability_holdout": _reliability(y_test, p_test_platt),
        "pattern_rule_acc": pattern_eval["accuracy"],
        "pattern_evaluation": pattern_eval,
        "feature_schema_version": 2,
        "train_rows": int(len(train_idx)),
        "holdout_rows": int(len(test_idx)),
    }
    lines = [
        f"train rows: {len(train_idx)}, holdout rows: {len(test_idx)}",
        f"holdout AUC: {auc:.4f}  Platt Brier: {brier:.4f}  post-shift Brier: {final_brier:.4f}",
        f"base rate train: {train_prior:.3f}  holdout: {float(frame.loc[test_idx, 'y'].mean()):.3f}",
        f"customer-disjoint AUC: {customer_auc:.4f}",
        f"exact production pattern agreement: {pattern_eval['accuracy']:.4f}",
        f"cleared none accuracy: {pattern_eval['cleared_none_accuracy']:.4f}",
        "pattern confusion (rows=truth, cols=prediction):",
        json.dumps(pattern_eval["confusion_matrix"], sort_keys=True),
    ]
    return artifact, "\n".join(lines)


def main() -> None:
    frame = pd.read_parquet(OUT / "case_features.parquet")
    artifact, report = fit_model(frame)
    OUT.mkdir(exist_ok=True)
    (OUT / "model.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    (OUT / "eval_report.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"wrote {OUT / 'model.json'}")


if __name__ == "__main__":
    main()
