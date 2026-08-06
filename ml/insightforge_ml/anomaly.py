"""Anomaly detection: rolling median/MAD z-scores.

MAD (median absolute deviation) rather than mean/stddev because business
series contain the very outliers we're hunting — a mean-based z-score lets a
big spike inflate sigma and hide itself. The rolling window keeps slow drifts
(growth, seasonality ramps) from being flagged as anomalies.
"""

from __future__ import annotations

import math
import statistics


def detect_anomalies(values: list[float], labels: list | None = None,
                     window: int = 7, threshold: float = 3.5) -> dict:
    """Flag points whose robust z-score vs the surrounding window exceeds
    `threshold` (3.5 is the standard Iglewicz-Hoaglin cutoff).

    Returns {method, threshold, anomalies: [{index, label, value, expected,
    score, direction}], checked}.
    """
    y = [float(v) if v is not None and math.isfinite(float(v)) else None
         for v in values]
    n = len(y)
    if n < 5:
        raise ValueError("Need at least 5 points to detect anomalies")
    window = max(5, min(int(window), n))
    half = window // 2
    anomalies = []
    for i, v in enumerate(y):
        if v is None:
            continue
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        neighbours = [y[j] for j in range(lo, hi) if j != i and y[j] is not None]
        if len(neighbours) < 3:
            continue
        med = statistics.median(neighbours)
        mad = statistics.median(abs(x - med) for x in neighbours)
        if mad == 0:
            spread = (statistics.pstdev(neighbours) or 1e-9)
            score = abs(v - med) / (spread * 1.4826)
        else:
            score = 0.6745 * abs(v - med) / mad
        if score >= threshold:
            anomalies.append({
                "index": i,
                "label": (labels[i] if labels and i < len(labels) else i),
                "value": round(v, 4), "expected": round(med, 4),
                "score": round(score, 2),
                "direction": "spike" if v > med else "drop"})
    anomalies.sort(key=lambda a: -a["score"])
    return {"method": "rolling-mad-zscore", "threshold": threshold,
            "window": window, "checked": sum(1 for v in y if v is not None),
            "anomalies": anomalies}
