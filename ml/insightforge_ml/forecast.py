"""Holt's linear-trend exponential smoothing with an honest confidence band.

Why Holt and not an LLM/deep model: SMB metric series are short (weeks to a
couple of years), and double exponential smoothing is the textbook-correct,
explainable baseline for level+trend series. It fits in microseconds, has two
interpretable knobs, and degrades gracefully on flat or noisy series.
"""

from __future__ import annotations

import math


def _holt_fit(y: list[float], alpha: float, beta: float):
    level, trend = y[0], (y[1] - y[0]) if len(y) > 1 else 0.0
    fitted = [level + trend]
    for value in y[1:]:
        prev_level = level
        level = alpha * value + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        fitted.append(level + trend)
    return level, trend, fitted


def _sse(y: list[float], fitted: list[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(y, fitted))


def forecast_series(values: list[float], horizon: int = 6) -> dict:
    """Forecast `horizon` future points for an ordered numeric series.

    Returns {method, points: [{step, forecast, lo, hi}], trend_per_step,
    residual_std}. Grid-searches the two smoothing constants on one-step-ahead
    error; the band is ±1.96·residual_std·sqrt(step) — widening honestly with
    distance, as uncertainty genuinely compounds.
    """
    y = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(y) < 3:
        raise ValueError("Need at least 3 numeric points to forecast")
    horizon = max(1, min(int(horizon), 36))

    best = None
    for a10 in range(1, 10):
        for b10 in range(1, 10):
            alpha, beta = a10 / 10, b10 / 10
            level, trend, fitted = _holt_fit(y, alpha, beta)
            err = _sse(y[1:], fitted[:-1])
            if best is None or err < best[0]:
                best = (err, alpha, beta, level, trend, fitted)
    err, alpha, beta, level, trend, fitted = best
    residuals = [a - b for a, b in zip(y[1:], fitted[:-1])]
    dof = max(1, len(residuals) - 2)
    residual_std = math.sqrt(sum(r * r for r in residuals) / dof)

    points = []
    for step in range(1, horizon + 1):
        point = level + trend * step
        band = 1.96 * residual_std * math.sqrt(step)
        points.append({"step": step, "forecast": round(point, 4),
                       "lo": round(point - band, 4), "hi": round(point + band, 4)})
    return {"method": "holt-linear", "alpha": alpha, "beta": beta,
            "trend_per_step": round(trend, 4),
            "residual_std": round(residual_std, 4), "points": points}


def holt_winters_additive(values: list[float], season_length: int,
                          horizon: int = 6) -> dict:
    """R7: additive Holt-Winters. Needs >= 2 full seasons; refuses
    otherwise (no fake seasonality)."""
    m = season_length
    n = len(values)
    if m < 2 or n < 2 * m:
        raise ValueError(f"Need at least 2 full seasons "
                         f"({2 * m} points) for season_length={m}; "
                         f"got {n}")
    alpha, beta, gamma = 0.3, 0.05, 0.2
    season_avgs = [sum(values[i * m:(i + 1) * m]) / m
                   for i in range(n // m)]
    level = season_avgs[0]
    trend = (season_avgs[1] - season_avgs[0]) / m
    seasonal = [values[i] - season_avgs[0] for i in range(m)]
    resid = []
    for i, v in enumerate(values):
        s_i = seasonal[i % m]
        pred = level + trend + s_i
        resid.append(v - pred)
        last_level = level
        level = alpha * (v - s_i) + (1 - alpha) * (level + trend)
        trend = beta * (level - last_level) + (1 - beta) * trend
        seasonal[i % m] = gamma * (v - level) + (1 - gamma) * s_i
    rs = (sum(r * r for r in resid) / len(resid)) ** 0.5
    points = []
    for h in range(1, horizon + 1):
        f = level + h * trend + seasonal[(n + h - 1) % m]
        points.append({"step": h, "forecast": round(f, 4),
                       "lo": round(f - 1.96 * rs, 4),
                       "hi": round(f + 1.96 * rs, 4)})
    return {"method": "holt-winters-additive", "season_length": m,
            "residual_std": round(rs, 4), "points": points}
