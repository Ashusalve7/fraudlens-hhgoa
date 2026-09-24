from __future__ import annotations

import copy
import json
import math

import pandas as pd
import pytest

from agent.decision import MODEL_FEATURES, Calibrator
from eval.train import fit_model


def test_checked_in_artifact_loads_with_exact_feature_contract():
    calibrator = Calibrator()
    assert calibrator.features == MODEL_FEATURES
    assert calibrator.scale
    assert calibrator.train_base_rate == pytest.approx(0.8190750059908939)


def test_platt_runtime_uses_the_same_training_bounds(production_model):
    production_model["platt"].update({"low": 0.0, "high": 1.0})
    production_model["coef"][0] = 20.0
    calibrator = Calibrator(model=production_model)
    inside = {name: 0 for name in MODEL_FEATURES}
    inside["flagged_amount"] = 1.0
    outside = {name: 0 for name in MODEL_FEATURES}
    outside["flagged_amount"] = 20.0
    assert calibrator.score(inside) == calibrator.score(outside)


def test_extreme_scores_and_response_updates_remain_finite_and_do_not_use_fixed_endpoints():
    calibrator = Calibrator(
        model={
            "features": list(MODEL_FEATURES),
            "scaler_mean": [0.0] * 16,
            "scaler_scale": [1.0] * 16,
            "coef": [1000.0] + [0.0] * 15,
            "intercept": 0.0,
            "platt": {"mean": 0.0, "std": 1.0, "w": 1.0, "b": 0.0},
            "train_base_rate": 0.5,
            "exam_base_rate": 0.5,
            "temperature": 1.0,
        }
    )
    high = {name: 0 for name in MODEL_FEATURES}
    high["flagged_amount"] = 1e300
    p_history, p_exam = calibrator.score(high)
    assert math.isfinite(p_history)
    assert math.isfinite(p_exam)
    assert 0 <= p_history <= 1
    assert 0 <= p_exam <= 1

    denied = calibrator.update_for_response(0.5, "denied")
    confirmed = calibrator.update_for_response(0.5, "confirmed")
    assert 0.8 < denied < 0.95
    assert 0.05 < confirmed < 0.2
    assert denied != 0.9
    assert confirmed != 0.1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda model: model.pop("coef"),
        lambda model: model.__setitem__("features", ["wrong"] + MODEL_FEATURES[1:]),
        lambda model: model["scaler_mean"].__setitem__(0, math.nan),
        lambda model: model["scaler_scale"].__setitem__(0, 0),
        lambda model: model["platt"].__setitem__("std", 0),
        lambda model: model["platt"].pop("high"),
        lambda model: model.__setitem__("train_base_rate", 0),
        lambda model: model.__setitem__("temperature", math.nan),
        lambda model: model.__setitem__("response_likelihood", {"denied": 0}),
    ],
)
def test_malformed_model_artifacts_fail_closed(production_model, mutate):
    model = copy.deepcopy(production_model)
    mutate(model)
    with pytest.raises(ValueError):
        Calibrator(model=model)


def test_unknown_response_and_invalid_probability_are_rejected(production_model):
    calibrator = Calibrator(model=production_model)
    with pytest.raises(ValueError, match="unsupported"):
        calibrator.update_for_response(0.5, "maybe")
    with pytest.raises(ValueError, match="probability"):
        calibrator.update_for_response(1.1, "denied")


def training_frame(count: int, *, one_class: bool = False) -> pd.DataFrame:
    rows = []
    for index in range(count):
        row = {name: float(index % 3) for name in MODEL_FEATURES}
        row.update(
            {
                "opened_at": pd.Timestamp("2016-07-01") + pd.Timedelta(days=index),
                "outcome": "confirmed_fraud" if one_class or index % 2 else "cleared",
                "pattern": "none",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def test_fit_model_emits_a_strict_loadable_schema_and_standard_json(production_model):
    artifact, report = fit_model(training_frame(8))
    assert artifact["features"] == MODEL_FEATURES
    assert set(artifact["platt"]) >= {"mean", "std", "w", "b", "low", "high"}
    assert "holdout AUC" in report
    json.dumps(artifact, allow_nan=False)
    Calibrator(model=artifact)


def test_one_class_training_stays_finite_and_emits_a_loadable_artifact():
    artifact, _ = fit_model(training_frame(5, one_class=True))
    assert 0 < artifact["train_base_rate"] < 1
    assert artifact["pattern_evaluation"]["cleared_none_accuracy"] is None
    json.dumps(artifact, allow_nan=False)
    Calibrator(model=artifact)
