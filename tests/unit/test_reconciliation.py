"""SYNTHETIC tests for hierarchical reconciliation (DE = sum of 4 areas)."""

import numpy as np

from gridmind.forecasting.control_areas import (
    g_bottom_up,
    g_mint,
    g_ols,
    reconcile,
    shrink_covariance,
    summing_matrix,
    zone_weights,
)

S = summing_matrix()
RNG = np.random.default_rng(0)


def _base(n=200, incoherence=500.0):
    bottom = RNG.normal(15_000, 2_000, size=(n, 4))
    total = bottom.sum(axis=1, keepdims=True) + RNG.normal(0, incoherence, size=(n, 1))
    return np.hstack([total, bottom])


def _coherent(y):
    return np.allclose(y[:, 0], y[:, 1:].sum(axis=1), atol=1e-6)


def test_all_methods_produce_coherent_forecasts():
    b = _base()
    w, _ = shrink_covariance(RNG.normal(size=(500, 5)) * [800, 300, 300, 300, 300])
    for g in [g_bottom_up(), g_ols(S), g_mint(S, w)]:
        assert _coherent(reconcile(b, g, S))


def test_bottom_up_keeps_areas_and_replaces_total():
    b = _base()
    r = reconcile(b, g_bottom_up(), S)
    assert np.allclose(r[:, 1:], b[:, 1:])
    assert np.allclose(r[:, 0], b[:, 1:].sum(axis=1))


def test_projections_leave_coherent_input_unchanged():
    b = _base(incoherence=0.0)
    w, _ = shrink_covariance(RNG.normal(size=(500, 5)))
    for g in [g_ols(S), g_mint(S, w)]:
        assert np.allclose(reconcile(b, g, S), b, atol=1e-6)


def test_mint_with_identity_covariance_equals_ols():
    b = _base()
    assert np.allclose(reconcile(b, g_mint(S, np.eye(5)), S), reconcile(b, g_ols(S), S))


def test_mint_trusts_the_less_noisy_level():
    # Total forecast is very noisy, areas precise -> MinT should be close to bottom-up.
    b = _base(incoherence=3_000.0)
    w = np.diag([3_000.0**2, 50.0**2, 50.0**2, 50.0**2, 50.0**2])
    r_mint = reconcile(b, g_mint(S, w), S)
    r_bu = reconcile(b, g_bottom_up(), S)
    assert np.abs(r_mint - r_bu).max() < 200


def test_shrinkage_intensity_in_unit_interval():
    _, lam = shrink_covariance(RNG.normal(size=(50, 5)))
    assert 0.0 <= lam <= 1.0


def test_zone_weights_partition_germany():
    areas = ["DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"]
    union = {}
    for a in areas:
        union.update(zone_weights(a))
    assert union == zone_weights("DE") and "luxembourg" not in union
