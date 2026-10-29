"""Tables and charts for notebooks/dashboard.ipynb.

Everything is computed "as of" a date from the same signal functions as the daily command,
so the dashboard and `python -m ornn_analysis.daily` always agree.
"""
import shutil

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import signals
from .config import CACHE_DIR
from .daily import ENERGY_LABEL, STATUS_LABEL, load_all

PRESSURE = {"tight": "Up", "tightening": "Up, building", "watch": "Mild", "slack": "Low"}


# ---------------------------------------------------------------- data

def load(refresh: bool = False) -> tuple[dict, list[str]]:
    """All dashboard data. Downloads anything older than 24 hours; refresh=True re-downloads everything."""
    if refresh and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    return load_all()


def latest_date(data: dict) -> pd.Timestamp:
    return data["prices"].dropna(how="all").index.max()


def _change(s: pd.Series, asof, days: int) -> float:
    s = s.loc[:pd.Timestamp(asof)].dropna()
    if s.empty:
        return np.nan
    before = s.asof(s.index[-1] - pd.Timedelta(days=days))
    return 100 * (s.iloc[-1] / before - 1) if pd.notna(before) and before else np.nan


# ---------------------------------------------------------------- tables

def gpu_table(data: dict, asof) -> pd.DataFrame:
    """Per GPU: price, recent change, how full the market is, and the pressure that puts on prices."""
    sc = signals.scarcity(data["prices"], data["util"], asof)
    return pd.DataFrame({
        "Price ($/hr)": sc["price"].astype(float).round(2),
        "Price, 7 days": sc["price_7d_%"].map(lambda v: f"{v:+.0f}%"),
        "Price, 30 days": sc["price_30d_%"].map(lambda v: f"{v:+.0f}%"),
        "Utilization (7-day avg)": (100 * sc["util_7d"].astype(float)).map(lambda v: f"{v:.0f}%"),
        "Change, 4 weeks": sc["util_change_4w_pp"].map(lambda v: f"{v:+.0f} pts"),
        "Status": sc["status"].map(STATUS_LABEL),
        "Price pressure": sc["status"].map(PRESSURE),
    })


def energy_by_gpu(data: dict, asof, shuffles: int = 300) -> pd.DataFrame:
    """The energy check (signals.energy_watch) for every GPU, one row per GPU and energy input."""
    rows = []
    for gpu in data["prices"].columns:
        price = data["prices"][gpu].loc[:pd.Timestamp(asof)].dropna()
        if len(price) < 180:        # need ~6 months of weekly changes for a meaningful test
            continue
        res = signals.energy_watch(price, data["energy"], asof, shuffles=shuffles)
        for d, r in res.iterrows():
            rows.append({"GPU": gpu, "Input": ENERGY_LABEL.get(d, d), "Strongest lead (weeks)": int(r["best_lag_weeks"]),
                         "Correlation": r["corr"], "Older year": r["corr_first_half"], "Latest year": r["corr_second_half"],
                         "Chance %": r["chance_any_lag_%"], "Verdict": r["verdict"]})
    return pd.DataFrame(rows)


def inputs_table(data: dict, asof, energy: pd.DataFrame) -> pd.DataFrame:
    """One row per physical input: what it's doing now, whether it moves GPU prices, and which way it pushes."""
    rows = []
    sc = signals.scarcity(data["prices"], data["util"], asof)
    n_full = int((sc.status == "tight").sum())
    rows.append({"Input": "Utilization (scarcity)", "Route": "Scarcity",
                 "Now": f"{n_full} of {len(sc)} GPUs full (85%+ used)",
                 "Evidence it moves GPU prices": "Strong: price jumps came after utilization passed ~85% for all 6 GPUs, "
                                                 "on the way up and down (2026)",
                 "Pressure now": "Up" if n_full >= len(sc) / 2 else "Mixed" if n_full else "Low"})

    s = signals.supply_pipeline(data["construction"], asof) if data.get("construction") is not None else {}
    if s:
        rows.append({"Input": "Data-center construction (Census)", "Route": "Capacity",
                     "Now": f"{s['growth_yoy_%']:+.0f}% vs a year earlier ({pd.Timestamp(s['latest_month'] + '-01'):%b %Y}), {s['direction']}",
                     "Evidence it moves GPU prices": "Medium-low: slower construction was followed by a tighter market "
                                                     "6-9 months later, for all 6 GPUs; one cycle observed",
                     "Pressure now": {"accelerating": "Easing, months ahead", "slowing": "Up, months ahead",
                                      "steady": "Neutral"}[s["direction"]]})

    if "DDR5 16Gb chip" in data["memory"]:
        ddr5 = data["memory"]["DDR5 16Gb chip"].loc[:pd.Timestamp(asof)].dropna()
        c30 = _change(ddr5, asof, 30)
        rows.append({"Input": "Memory: DDR5 spot (Ornn)", "Route": "Capacity",
                     "Now": f"${ddr5.iloc[-1]:.2f}, {c30:+.0f}% in 30 days, {_change(ddr5, asof, 365):+.0f}% in a year",
                     "Evidence it moves GPU prices": "Low-medium: the shortage started Oct 2025 as utilization began "
                                                     "rising; memory-heavy GPUs rose most; no week-to-week link",
                     "Pressure now": "Up, slowly" if c30 > 3 else "Easing" if c30 < -3 else "Neutral"})

    for col, label in ENERGY_LABEL.items():
        if col not in data["energy"]:
            continue
        e = energy[energy.Input == label] if not energy.empty else energy
        lasting = e.loc[e.Verdict == "possible signal - check", "GPU"].tolist() if not e.empty else []
        one = e.loc[e.Verdict == "one period only", "GPU"].tolist() if not e.empty else []
        if lasting:
            evidence = f"Possible lasting link for {', '.join(lasting)}: check"
        elif one:
            evidence = f"No lasting link for any GPU (one-off episode for {', '.join(one)})"
        else:
            evidence = "No link for any GPU"
        s_ = data["energy"][col].loc[:pd.Timestamp(asof)].dropna()
        rows.append({"Input": label, "Route": "Cost (power)",
                     "Now": f"${s_.iloc[-1]:.2f}, {_change(s_, asof, 30):+.0f}% in 30 days",
                     "Evidence it moves GPU prices": evidence + "; power is ~3-5% of a GPU-hour",
                     "Pressure now": "Check" if lasting else "None detected"})
    return pd.DataFrame(rows).set_index("Input")


def gpu_correlations(data: dict, asof, start="2025-09-23") -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    """Week-to-week correlation between GPUs, for price and utilization, since all six were trading."""
    p = data["prices"].loc[start:pd.Timestamp(asof)].resample("W-FRI").last().pct_change(fill_method=None)
    u = data["util"].loc[start:pd.Timestamp(asof)].resample("W-FRI").mean().diff()
    pc, uc = p.corr().round(2), u.corr().round(2)
    off = lambda c: c.where(~np.eye(len(c), dtype=bool)).stack().mean()
    return pc, uc, float(off(pc)), float(off(uc))


# ---------------------------------------------------------------- charts

def plot_scarcity(data: dict, asof, days: int = 365):
    p = data["prices"].loc[:pd.Timestamp(asof)]
    u = data["util"].loc[:pd.Timestamp(asof)].rolling(7, min_periods=4).mean()
    start = pd.Timestamp(asof) - pd.Timedelta(days=days)
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharex=True)
    for ax, g in zip(axes.flat, p.columns):
        p[g].loc[start:].plot(ax=ax, color="black", lw=1.2, title=g)
        ax.set_ylabel("$ per hour (black)")
        ax2 = ax.twinx()
        u[g].loc[start:].plot(ax=ax2, color="tab:orange", lw=1.2)
        ax2.axhline(signals.TIGHT, color="tab:red", ls=":", lw=1)
        ax2.set_ylim(0, 1.05)
        ax2.set_ylabel("utilization (orange)")
    fig.suptitle("Price (black) vs 7-day utilization (orange); red line = 85% used", y=1.0)
    fig.tight_layout()
    return fig


def plot_supply(data: dict, asof, lag_months: int = signals.SUPPLY_LEAD_MONTHS):
    c = data["construction"].dropna()
    c = c[c.index + pd.DateOffset(months=2) <= pd.Timestamp(asof)]          # only what Census had published
    growth = (100 * c.pct_change(12)).shift(lag_months, freq="MS")
    util = data["util"].loc[:pd.Timestamp(asof)].resample("MS").mean().mean(axis=1)
    start = data["util"].dropna(how="all").index.min()
    fig, ax = plt.subplots(figsize=(12, 4.5))
    growth.loc[start:pd.Timestamp(asof)].plot(ax=ax, color="tab:blue", lw=1.5,
                                              label=f"Construction growth vs a year earlier, {lag_months} months earlier (%)")
    ax.invert_yaxis()
    ax.set_ylabel("construction growth, % (axis flipped)")
    ax2 = ax.twinx()
    util.loc[start:].plot(ax=ax2, color="tab:orange", lw=1.5, label="Average utilization, all GPUs")
    ax2.set_ylabel("utilization")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="lower right", fontsize=8)
    ax.set_title("Slower construction (blue, flipped axis) vs utilization months later (orange)")
    fig.tight_layout()
    return fig


def plot_memory(data: dict, asof, start: str = "2025-01-01"):
    ddr5 = data["memory"]["DDR5 16Gb chip"].loc[start:pd.Timestamp(asof)]
    p = data["prices"].loc[start:pd.Timestamp(asof)]
    ratio = (p["H200"] / p["H100 SXM"]).rolling(14, min_periods=7).mean()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    ddr5.plot(ax=a1, color="tab:purple", title="DDR5 16Gb spot price, Ornn ($)")
    ratio.plot(ax=a2, color="black", title="H200 price ÷ H100 price (same chip, more memory; 14-day avg)")
    for ax in (a1, a2):
        ax.axvline(pd.Timestamp("2025-10-01"), color="grey", ls="--", lw=0.8)
    fig.suptitle("Grey line: October 2025, when memory prices took off", y=1.0)
    fig.tight_layout()
    return fig


def plot_gpu_prices(data: dict, asof, start: str = "2025-09-23"):
    p = data["prices"].loc[start:pd.Timestamp(asof)].ffill()
    ax = (100 * p / p.bfill().iloc[0]).plot(figsize=(12, 4.5), lw=1.2,
                                            title=f"GPU prices, rebased to 100 on {pd.Timestamp(start):%d %b %Y}")
    ax.axhline(100, color="grey", lw=0.5)
    ax.figure.tight_layout()
    return ax.figure
