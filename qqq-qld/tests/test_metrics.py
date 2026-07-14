import numpy as np
import pandas as pd

from qqq_qld.metrics import drawdown, performance_metrics


def test_constant_positive_returns_have_expected_cagr():
    returns = pd.Series(np.repeat(0.001, 252))
    metrics = performance_metrics(returns)
    assert np.isclose(metrics["cagr"], (1.001**252) - 1)
    assert metrics["max_drawdown"] == 0


def test_drawdown_path():
    returns = pd.Series([0.10, -0.20, 0.25])
    result = drawdown(returns)
    assert np.isclose(result.iloc[1], -0.20)
    assert np.isclose(result.iloc[-1], 0.0)
