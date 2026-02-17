import numpy as np
import pandas as pd

from services.risk import (
    _calculate_var_cvar,
    _calculate_drawdown_metrics,
    _score_from_range,
    _calculate_beta,
)


def test_calculate_var_cvar_basic():
    returns = pd.Series([-0.10, 0.02, -0.05, 0.03, 0.01])
    var_95, cvar_95 = _calculate_var_cvar(returns, 0.05)

    expected_var = -float(np.quantile(returns, 0.05))
    tail = returns[returns <= np.quantile(returns, 0.05)]
    expected_cvar = -float(tail.mean())

    assert var_95 == expected_var
    assert cvar_95 == expected_cvar


def test_calculate_drawdown_metrics():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    prices = pd.Series([100, 110, 105, 90, 95, 120], index=dates)

    metrics = _calculate_drawdown_metrics(prices)

    assert metrics["max_drawdown"] is not None
    assert round(metrics["max_drawdown"], 4) == round(1 - (90 / 110), 4)
    assert metrics["max_drawdown_days"] == 3
    assert metrics["recovery_days"] == 2


def test_score_from_range_inverse():
    score_low = _score_from_range(0.5, 1.0, 2.0, higher_is_risk=False)
    score_high = _score_from_range(2.0, 1.0, 2.0, higher_is_risk=False)

    assert score_low == 100.0
    assert score_high == 0.0


def test_calculate_beta_identity():
    returns = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01])
    beta = _calculate_beta(returns, returns)

    assert round(beta, 6) == 1.0
