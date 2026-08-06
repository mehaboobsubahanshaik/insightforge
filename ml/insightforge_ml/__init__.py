"""InsightForge ML package.

Deliberately dependency-light (pure Python + stdlib): these models run inside
the API request path for SMB-scale data, so they must be fast, deterministic
and impossible to break via heavyweight native dependencies. The interfaces
are the contract — a future upgrade can swap in statsmodels/Prophet/Azure ML
behind the same functions (see docs/adr/0011).
"""

from .anomaly import detect_anomalies
from .forecast import forecast_series

__all__ = ["detect_anomalies", "forecast_series"]
