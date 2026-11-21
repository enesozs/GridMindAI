"""SYNTHETIC profiles for the storage peak-shaving LP."""

import numpy as np
import pytest

from gridmind.optimization.storage import Fleet, evaluate, plan

FLEET = Fleet()


def _check_physics(s, fleet=FLEET):
    eta = fleet.eta
    soc = s.soc_mwh
    assert np.allclose(soc[1:], soc[:-1] + eta * s.charge_mw - s.discharge_mw / eta, atol=1e-3)
    assert soc[0] == pytest.approx(fleet.soc_start_frac * fleet.energy_mwh, abs=1e-3)
    assert soc[-1] == pytest.approx(fleet.soc_start_frac * fleet.energy_mwh, abs=1e-3)
    assert soc.min() >= fleet.soc_min_frac * fleet.energy_mwh - 1e-3
    assert soc.max() <= fleet.soc_max_frac * fleet.energy_mwh + 1e-3
    assert (s.charge_mw <= fleet.power_mw + 1e-6).all() and (s.discharge_mw <= fleet.power_mw + 1e-6).all()


def test_flat_profile_needs_no_dispatch():
    s = plan(np.full(24, 30_000.0))
    assert s.status == "optimal"
    assert s.charge_mw.sum() == 0 and s.discharge_mw.sum() == 0
    _check_physics(s)


def test_single_peak_is_shaved_by_discharging_at_the_peak():
    f = np.full(24, 30_000.0)
    f[18] = 34_000.0
    s = plan(f)
    _check_physics(s)
    assert s.discharge_mw[18] == pytest.approx(2_000.0, abs=1)  # full power at the peak
    assert s.planned_peak_mw == pytest.approx(32_000.0, abs=1)
    ev = evaluate(s, f)
    assert ev["peak_reduction_mw"] == pytest.approx(2_000.0, abs=1)


def test_energy_limit_binds_for_a_broad_peak():
    f = np.full(24, 30_000.0)
    f[12:20] = 34_000.0  # 8 h peak: 2 GW for 8 h needs 16 GWh > usable energy
    s = plan(f)
    _check_physics(s)
    assert s.planned_peak_mw > 32_000.0  # cannot shave the full 2 GW for 8 hours


@pytest.mark.parametrize("n", [23, 25])
def test_dst_day_lengths(n):
    f = 30_000.0 + 3_000.0 * np.sin(np.linspace(0, 2 * np.pi, n))
    s = plan(f)
    assert s.status == "optimal" and len(s.charge_mw) == n and len(s.soc_mwh) == n + 1
    _check_physics(s)


def test_plan_on_wrong_forecast_can_worsen_realised_peak():
    forecast = np.full(24, 30_000.0)
    forecast[6] = 34_000.0
    actual = np.full(24, 30_000.0)
    actual[18] = 34_000.0  # the real peak is elsewhere
    ev = evaluate(plan(forecast), actual)
    assert ev["peak_reduction_mw"] <= 0  # discharging at the wrong hour cannot help the real peak


def test_nan_forecast_rejected():
    with pytest.raises(ValueError):
        plan(np.array([1.0, np.nan]))
