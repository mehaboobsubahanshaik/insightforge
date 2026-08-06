# ADR 0011 - ML: explainable stdlib models behind stable contracts

**Status**: accepted

forecast_series() = Holt linear trend with grid-searched smoothing and an honest +-1.96*sigma*sqrt(h) band; detect_anomalies() = rolling median/MAD robust z-score (Iglewicz-Hoaglin 3.5). Reasons: SMB series are short; these run in-request in microseconds; every output is explainable to a non-analyst; zero native dependencies keeps the container slim. Upgrade path: keep the function signatures, swap internals (Holt-Winters seasonal is backlog item 4) - callers and UI never change.
