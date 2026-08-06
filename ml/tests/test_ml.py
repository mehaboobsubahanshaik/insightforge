"""Unit tests for the ML package — deterministic by construction."""

import math

import pytest
from insightforge_ml import detect_anomalies, forecast_series


def test_forecast_recovers_linear_trend():
    y = [100 + 10 * i for i in range(12)]  # perfect line: 100,110,...210
    out = forecast_series(y, horizon=3)
    assert out["method"] == "holt-linear"
    # next points should continue the line closely
    f1 = out["points"][0]["forecast"]
    assert abs(f1 - 220) < 2
    assert abs(out["trend_per_step"] - 10) < 0.5
    # near-zero residuals => tight band
    assert out["points"][0]["hi"] - out["points"][0]["lo"] < 4


def test_forecast_band_widens_with_horizon():
    y = [100, 130, 95, 140, 110, 150, 120, 160, 135, 170]
    out = forecast_series(y, horizon=6)
    w1 = out["points"][0]["hi"] - out["points"][0]["lo"]
    w6 = out["points"][5]["hi"] - out["points"][5]["lo"]
    assert w6 > w1 * 2  # sqrt(6) ≈ 2.45


def test_forecast_needs_three_points():
    with pytest.raises(ValueError):
        forecast_series([1, 2], horizon=3)


def test_anomaly_flags_the_spike_only():
    y = [100, 102, 98, 101, 99, 500, 103, 97, 100, 101]
    out = detect_anomalies(y, labels=[f"d{i}" for i in range(10)])
    assert len(out["anomalies"]) == 1
    a = out["anomalies"][0]
    assert a["index"] == 5 and a["direction"] == "spike" and a["label"] == "d5"
    assert a["score"] > 10


def test_anomaly_robust_to_drift():
    y = [100 + 3 * i for i in range(30)]  # steady growth is NOT anomalous
    out = detect_anomalies(y)
    assert out["anomalies"] == []


def test_anomaly_detects_drop():
    y = [200.0] * 6 + [40.0] + [200.0] * 6
    out = detect_anomalies(y)
    assert out["anomalies"][0]["direction"] == "drop"


def test_anomaly_handles_gaps():
    y = [100, None, 101, 99, math.nan, 100, 400, 100, 99]
    cleaned = [v if (v is not None and not (isinstance(v, float) and math.isnan(v)))
               else None for v in y]
    out = detect_anomalies(cleaned)
    assert any(a["index"] == 6 for a in out["anomalies"])
