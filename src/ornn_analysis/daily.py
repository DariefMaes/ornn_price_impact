"""Daily signals, printed to the terminal.

    python -m ornn_analysis.daily                    # readable report for today
    python -m ornn_analysis.daily --asof 2026-05-15  # as it would have looked on a past date
    python -m ornn_analysis.daily --json             # same signals as one JSON object, for other systems

Writes no files (downloads are cached in data/cache/ for 24h). Exits with code 1 only if the
core Ornn data can't be loaded; if Yahoo or Census fails, the rest still prints.
"""
import argparse
import json
import logging
import sys
import textwrap
from datetime import datetime, timezone

import pandas as pd

from . import signals
from .data import LOADERS, load_census_construction, load_ornn_memory
from .explore import load_gpus, load_utilization
from .series import DRIVERS, MEMORY

log = logging.getLogger("ornn_daily")
ENERGY = ["wti_oil", "brent_oil", "henry_hub_gas"]


def _try(name, fn, failures):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one source failing shouldn't stop the report
        failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:100]}")
        return None


def load_all() -> tuple[dict, list[str]]:
    failures = []
    data = {"prices": load_gpus(), "util": load_utilization()}

    def drivers(names):
        cols = {}
        for n in names:
            source, ticker, _, _ = DRIVERS[n]
            s = _try(n, lambda: LOADERS[source](ticker), failures)
            if s is not None:
                cols[n] = s
        return pd.DataFrame(cols)

    data["energy"] = drivers(ENERGY)
    mem = {}
    for name, memory_id in MEMORY.items():
        s = _try(f"ornn_memory_{memory_id}", lambda: load_ornn_memory(memory_id), failures)
        if s is not None:
            mem[name] = s
    data["memory"] = pd.DataFrame(mem)
    data["construction"] = _try("census_data_center", lambda: load_census_construction("Data center"), failures)
    return data, failures


def compute(data: dict, asof) -> dict:
    return {
        "asof": pd.Timestamp(asof).date().isoformat(),
        "scarcity": signals.scarcity(data["prices"], data["util"], asof),
        "supply": signals.supply_pipeline(data["construction"], asof) if data["construction"] is not None else {},
        "memory": signals.memory(data["prices"], data["memory"], asof) if not data["memory"].empty else {},
        "energy": (signals.energy_watch(data["prices"]["H100 SXM"], data["energy"], asof)
                   if not data["energy"].empty else pd.DataFrame()),
        "quality": signals.data_quality(data["prices"], data["util"], asof),
    }


STATUS_LABEL = {"tight": "Full", "tightening": "Filling up", "watch": "Busy", "slack": "Room available"}
ENERGY_LABEL = {"wti_oil": "WTI oil", "brent_oil": "Brent oil", "henry_hub_gas": "US natural gas"}
ENERGY_NOUN = {"wti_oil": "oil", "brent_oil": "oil", "henry_hub_gas": "gas"}
WIDTH = 92


def _wrap(text: str, indent: str = "  ", hang: int = 0) -> list[str]:
    """Wrap to WIDTH. Continuation lines line up under the text, not under a bullet or label."""
    first_width = len(indent) + hang
    return textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=" " * first_width)


def _energy_sentence(name: str, row) -> str:
    if row["verdict"] == "possible signal - check":
        return (f"Possible link: moves line up when {name} leads by {row['best_lag_weeks']} weeks, in both of the "
                f"last two years (correlation {row['corr_first_half']:.2f} and {row['corr_second_half']:.2f}). "
                f"Check before trusting.")
    if row["verdict"] == "one period only":
        return (f"No lasting link. Moves line up when {name} leads by {row['best_lag_weeks']} weeks, but only in "
                f"the past year (correlation {row['corr_second_half']:.2f}), not the year before "
                f"({row['corr_first_half']:.2f}): one episode, not a pattern.")
    return (f"No link. The strongest match (correlation {row['corr']:.2f}) is the kind of thing chance "
            f"produces {row['chance_any_lag_%']:.0f}% of the time.")


def summary(r: dict) -> list[str]:
    sc = r["scarcity"]
    full = sc.index[sc.status == "tight"].tolist()
    filling = sc.index[sc.status == "tightening"].tolist()
    spare = sc["spare_capacity_%"].astype(float)
    if len(full) == len(sc):
        line = (f"The market is full: all {len(sc)} GPUs have {spare.min():.0f}-{spare.max():.0f}% spare capacity. "
                f"This is the zone where prices have jumped before.")
    elif full:
        line = f"{len(full)} of {len(sc)} GPUs are full (85%+ used): {', '.join(full)}."
    else:
        line = f"No GPU is full (85%+ used); the most used is {sc['util_7d'].astype(float).idxmax()}."
    if filling:
        line += f" Filling up fast: {', '.join(filling)}."
    lines = [line]
    if r["supply"]:
        s = r["supply"]
        outlook = {"accelerating": f"the market should loosen around {s['effect_month']}",
                   "slowing": f"the market should tighten around {s['effect_month']}",
                   "steady": "no change in market tightness is expected"}[s["direction"]]
        lines.append(f"Data-center construction is {s['direction']} ({s['growth_yoy_%']:+.0f}% vs a year earlier). "
                     f"If the past pattern holds, {outlook}.")
    m = r["memory"]
    if "premium_H200/H100" in m:
        before = m["premium_H200/H100"] / (1 + m["premium_H200/H100_90d_change_%"] / 100)
        now = m["premium_H200/H100"]
        trend = "up from" if round(now, 1) > round(before, 1) else "down from" if round(now, 1) < round(before, 1) else "about the same as"
        line = f"An H200 costs {now:.1f}x an H100 (same chip, more memory), {trend} {before:.1f}x three months ago."
        chip = m.get("spot", {}).get("DDR5 16Gb chip")
        if chip:
            c30 = chip["change_30d_%"]
            move = "still rising" if c30 > 3 else "falling" if c30 < -3 else "flat"
            line = (f"Memory prices are {move}: DDR5 spot ${chip['price']:.2f} ({c30:+.0f}% in 30 days, "
                    f"{chip['change_1y_%']:+.0f}% in a year). ") + line
        lines.append(line)
    if not r["energy"].empty:
        lasting = r["energy"].index[r["energy"].verdict == "possible signal - check"].tolist()
        lines.append("Oil and gas: possible link from " + ", ".join(ENERGY_LABEL.get(d, d) for d in lasting)
                     + ", check the energy section." if lasting else "Oil and gas: no lasting link to GPU prices.")
    if r["quality"]:
        n = len(r["quality"])
        lines.append(f"{n} data-quality {'note' if n == 1 else 'notes'} to review (section 5).")
    return lines


def render(r: dict, failures: list[str]) -> str:
    asof = pd.Timestamp(r["asof"])
    title = f"GPU compute signals, {asof.day} {asof:%b %Y}"
    out = [title, "=" * len(title), "", "SUMMARY"]
    for line in summary(r):
        out.extend(_wrap(line, "  - "))

    def section(n, title, note=None):
        out.extend(["", f"{n}. {title}"])
        if note:
            out.extend(_wrap(note, "   "))
        out.append("")

    section(1, "How full is each GPU market?",
            "Prices have stayed flat while utilization is below ~85% and risen sharply above it. "
            "Utilization is a 7-day average, because demand peaks mid-week and drops at weekends.")
    sc = r["scarcity"]
    header = f"   {'GPU':<17}{'Price/hr':>9}{'7 days':>9}{'30 days':>9}{'Used':>8}{'Spare':>8}{'Last 4 wks':>12}   Status"
    out.append(header)
    for g, row in sc.iterrows():
        out.append(f"   {g:<17}{'$' + format(float(row['price']), '.2f'):>9}{float(row['price_7d_%']):>+8.1f}%"
                   f"{float(row['price_30d_%']):>+8.1f}%{100 * float(row['util_7d']):>7.0f}%{float(row['spare_capacity_%']):>7.0f}%"
                   f"{float(row['util_change_4w_pp']):>+8.1f} pts   {STATUS_LABEL[row['status']]}")
    out.extend([""] + _wrap("Last 4 wks = change in utilization over the past four weeks. Full = 85%+ used. "
                            "Filling up = 75-85% and up 3+ points in 4 weeks. Busy = 75-85%. "
                            "Room available = under 75%.", "   "))

    section(2, "Supply pipeline: US data-center construction (Census)")
    if r["supply"]:
        s = r["supply"]
        latest = pd.Timestamp(s["latest_month"] + "-01")
        out.extend(_wrap(f"Latest month: {latest:%B %Y}, building at a pace of ${s['spending_bn_annual_rate']:.0f}bn a year, "
                         f"{s['growth_yoy_%']:+.0f}% vs a year earlier (three months before it was "
                         f"{s['growth_yoy_3m_ago_%']:+.0f}%). Construction is {s['direction']}.", "   "))
        out.append("")
        out.extend(_wrap(f"In the past, faster construction was followed by a looser market about 9 months later, "
                         f"and slower construction by a tighter one. That points to {s['points_to']}. "
                         f"This is based on one cycle, so treat it as a forecast to check.", "   "))
    else:
        out.append("   Not available today.")

    section(3, "Memory",
            "Ornn memory spot prices (commodity DRAM: not the HBM on GPUs, but it reflects the same shortage, "
            "since HBM takes DRAM production capacity), and price ratios of GPU pairs that are the same chip "
            "with more memory.")
    m = r["memory"]
    if m:
        for key, label in [("H200/H100", "H200 vs H100"), ("RTXPRO6000/RTX5090", "RTX PRO 6000 vs RTX 5090")]:
            if f"premium_{key}" in m:
                before = m[f"premium_{key}"] / (1 + m[f"premium_{key}_90d_change_%"] / 100)
                out.append(f"   {label:<27}{m[f'premium_{key}']:.2f}x   (three months ago: {before:.2f}x)")
        if m.get("spot"):
            out.append("")
            out.append(f"   {'Spot price':<33}{'Now':>10}{'30 days':>10}{'90 days':>10}{'1 year':>10}")
            def pct(x):
                return f"{x:+.0f}%" if x == x else "n/a"   # NaN: series too short for this window
            for name, v in m["spot"].items():
                out.append(f"   {name:<33}{'$' + format(v['price'], ',.2f'):>10}{pct(v['change_30d_%']):>10}"
                           f"{pct(v['change_90d_%']):>10}{pct(v['change_1y_%']):>10}")
    else:
        out.append("   Not available today.")

    section(4, "Energy check: do oil or gas prices move before H100 prices?",
            "Based on weekly price changes over the last two years. A real link would have to beat chance "
            "and show up in both years.")
    if not r["energy"].empty:
        for d, row in r["energy"].iterrows():
            label = ENERGY_LABEL.get(d, d) + ":"
            out.extend(_wrap(f"{label:<16}{_energy_sentence(ENERGY_NOUN.get(d, d), row)}", "   ", hang=16))
    else:
        out.append("   Not available today.")

    section(5, "Data quality: check these before relying on the numbers",
            "Large price moves that utilization doesn't explain, and feeds that stopped updating. "
            "Two past index glitches (Aug 2024, Dec 2025) looked like this, but so can real moves in a full market.")
    for q in r["quality"] or ["Nothing to flag."]:
        out.extend(_wrap(q, "   - "))
    if failures:
        section(6, "Sources that failed to load today")
        for f in failures:
            out.extend(_wrap(f, "   - "))
    return "\n".join(out)


SCHEMA_VERSION = 1
STATUS_CODE = {"tight": "full", "tightening": "filling_up", "watch": "busy", "slack": "room_available"}


def _num(v):
    """Plain JSON numbers: numpy -> float, NaN -> null."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return v
    return None if v != v else round(v, 4)


def to_json(r: dict, failures: list[str]) -> dict:
    """The day's signals with stable field names, for storing or alerting in another system.

    Bump SCHEMA_VERSION whenever a field is renamed or removed, so consumers can tell.
    Utilization fields are 7-day averages (0-1); *_pct fields are percentages; *_pts are percentage points.
    """
    gpus = []
    for gpu, row in r["scarcity"].iterrows():
        gpus.append({
            "gpu": gpu,
            "price_usd_per_hour": _num(row["price"]),
            "price_change_7d_pct": _num(row["price_7d_%"]),
            "price_change_30d_pct": _num(row["price_30d_%"]),
            "utilization_7d_avg": _num(row["util_7d"]),
            "spare_capacity_pct": _num(row["spare_capacity_%"]),
            "utilization_change_4w_pts": _num(row["util_change_4w_pp"]),
            "days_at_or_above_85pct": int(row["days_above_85%"]),
            "status": STATUS_CODE[row["status"]],
            "last_price_date": row["last_price_date"],
            "last_utilization_date": row["last_util_date"],
        })
    s = r["supply"]
    supply = {
        "latest_month": s["latest_month"],
        "spending_usd_bn_annual_rate": _num(s["spending_bn_annual_rate"]),
        "growth_vs_year_earlier_pct": _num(s["growth_yoy_%"]),
        "growth_3_months_earlier_pct": _num(s["growth_yoy_3m_ago_%"]),
        "direction": s["direction"],
        "expected_effect": {"accelerating": "looser", "slowing": "tighter", "steady": "no_change"}[s["direction"]],
    } if s else None
    m = r["memory"]
    memory = {
        "h200_vs_h100_price_ratio": _num(m.get("premium_H200/H100")),
        "h200_vs_h100_change_90d_pct": _num(m.get("premium_H200/H100_90d_change_%")),
        "rtxpro6000_vs_rtx5090_price_ratio": _num(m.get("premium_RTXPRO6000/RTX5090")),
        "rtxpro6000_vs_rtx5090_change_90d_pct": _num(m.get("premium_RTXPRO6000/RTX5090_90d_change_%")),
        "spot_prices": [{"name": name, "ornn_memory_id": MEMORY.get(name), "price_usd": _num(v["price"]),
                         "change_30d_pct": _num(v["change_30d_%"]), "change_90d_pct": _num(v["change_90d_%"]),
                         "change_1y_pct": _num(v["change_1y_%"]), "last_date": v["last_date"]}
                        for name, v in m.get("spot", {}).items()],
    } if m else None
    energy = [{
        "driver": d,
        "best_lead_weeks": int(row["best_lag_weeks"]),
        "correlation": _num(row["corr"]),
        "correlation_older_year": _num(row["corr_first_half"]),
        "correlation_latest_year": _num(row["corr_second_half"]),
        "chance_pct": _num(row["chance_any_lag_%"]),
        "verdict": {"no signal": "no_link", "one period only": "one_period_only",
                    "possible signal - check": "possible_link"}[row["verdict"]],
    } for d, row in r["energy"].iterrows()]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": r["asof"],
        "gpus": gpus,
        "supply": supply,
        "memory": memory,
        "energy": energy,
        "data_quality_notes": r["quality"],
        "source_failures": failures,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", help="date to compute signals for (default: latest Ornn data)")
    ap.add_argument("--json", action="store_true", help="print the signals as one JSON object instead of the report")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    try:
        data, failures = load_all()
    except Exception as exc:  # noqa: BLE001
        log.error("could not load Ornn data (check ORNN_API_KEY in .env): %s", exc)
        return 1
    asof = pd.Timestamp(args.asof) if args.asof else data["prices"].dropna(how="all").index.max()
    r = compute(data, asof)
    print(json.dumps(to_json(r, failures), indent=2) if args.json else render(r, failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
