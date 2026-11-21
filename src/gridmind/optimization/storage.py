"""Day-ahead storage dispatch that shaves residual-load peaks, as a linear program.

Residual load r_t = load - wind - solar is the demand that conventional plants, imports
and storage must cover; its daily peak is the hour of greatest system stress. GridMind
uses residual load (open SMARD data) instead of prices, which are not used in this project.

For one delivery day with n hourly steps (23/24/25), a stylised storage fleet chooses
charge c_t and discharge d_t (MW) and state of charge s_t (MWh):

    minimise    P + eps * sum_t (c_t + d_t)            (peak, plus a tiny anti-cycling cost)
    subject to  P >= f_t + c_t - d_t                    for every hour (f = residual forecast)
                s_{t+1} = s_t + eta * c_t - d_t / eta   (eta = sqrt(round-trip efficiency))
                s_0 = s_n = soc_start
                soc_min <= s_t <= soc_max,  0 <= c_t, d_t <= power

"min max" is made linear with the auxiliary variable P (an epigraph formulation). The
schedule is planned on a forecast f and then applied to the realised residual load r; the
realised peak max_t(r_t + c_t - d_t) measures how much the forecast was worth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class Fleet:
    power_mw: float = 2_000.0
    energy_mwh: float = 8_000.0
    round_trip_eff: float = 0.90
    soc_min_frac: float = 0.10
    soc_max_frac: float = 0.90
    soc_start_frac: float = 0.50
    eps: float = 1e-4  # anti-cycling cost per MW moved (MW of peak per MW of throughput)

    @property
    def eta(self) -> float:
        return float(np.sqrt(self.round_trip_eff))


DEFAULT_FLEET = Fleet()


@dataclass(frozen=True)
class Schedule:
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    soc_mwh: np.ndarray  # length n + 1
    planned_peak_mw: float
    status: str

    @property
    def net_mw(self) -> np.ndarray:
        """Change in residual load caused by the fleet (+ charging, - discharging)."""
        return self.charge_mw - self.discharge_mw


def plan(forecast_mw: np.ndarray, fleet: Fleet = DEFAULT_FLEET) -> Schedule:
    """Solve the peak-shaving LP for one day of hourly residual-load forecasts."""
    f = np.asarray(forecast_mw, dtype=float)
    if np.isnan(f).any():
        raise ValueError("forecast contains NaN")
    n = len(f)
    # variable layout: c[0:n], d[n:2n], s[2n:3n+1], P[3n+1]
    nc, nd, ns = n, n, n + 1
    i_c, i_d, i_s, i_p = 0, n, 2 * n, 2 * n + ns
    nv = nc + nd + ns + 1

    cost = np.zeros(nv)
    cost[i_p] = 1.0
    cost[i_c:i_c + n] = fleet.eps
    cost[i_d:i_d + n] = fleet.eps

    # P >= f_t + c_t - d_t   ->   c_t - d_t - P <= -f_t
    a_ub = np.zeros((n, nv))
    for t in range(n):
        a_ub[t, i_c + t] = 1.0
        a_ub[t, i_d + t] = -1.0
        a_ub[t, i_p] = -1.0
    b_ub = -f

    # s_{t+1} - s_t - eta c_t + d_t / eta = 0 ; s_0 = s_start ; s_n = s_start
    a_eq = np.zeros((n + 2, nv))
    b_eq = np.zeros(n + 2)
    for t in range(n):
        a_eq[t, i_s + t + 1] = 1.0
        a_eq[t, i_s + t] = -1.0
        a_eq[t, i_c + t] = -fleet.eta
        a_eq[t, i_d + t] = 1.0 / fleet.eta
    s0 = fleet.soc_start_frac * fleet.energy_mwh
    a_eq[n, i_s] = 1.0
    b_eq[n] = s0
    a_eq[n + 1, i_s + n] = 1.0
    b_eq[n + 1] = s0

    bounds = ([(0.0, fleet.power_mw)] * (2 * n)
              + [(fleet.soc_min_frac * fleet.energy_mwh, fleet.soc_max_frac * fleet.energy_mwh)] * ns
              + [(None, None)])
    res = linprog(cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if res.status != 0:
        zero = np.zeros(n)
        return Schedule(zero, zero, np.full(ns, s0), float(f.max()), f"failed: {res.message}")
    x = res.x
    c, d = x[i_c:i_c + n], x[i_d:i_d + n]
    # Clean solver noise so tiny simultaneous charge/discharge does not show up in reports.
    c[c < 1e-6] = 0.0
    d[d < 1e-6] = 0.0
    return Schedule(c, d, x[i_s:i_s + ns], float(x[i_p]), "optimal")


def evaluate(schedule: Schedule, actual_mw: np.ndarray) -> dict:
    """Apply a planned schedule to realised residual load."""
    r = np.asarray(actual_mw, dtype=float)
    after = r + schedule.net_mw
    return {
        "peak_before_mw": float(r.max()),
        "peak_after_mw": float(after.max()),
        "peak_reduction_mw": float(r.max() - after.max()),
        "throughput_mwh": float(schedule.charge_mw.sum() + schedule.discharge_mw.sum()),
        "status": schedule.status,
    }
