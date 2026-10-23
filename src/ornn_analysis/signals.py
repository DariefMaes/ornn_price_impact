"""Daily signals, each computed "as of" a date using only data available up to that date.

Every function is pure (data in, numbers out) so the same code serves the daily run,
past dates (--asof) and the tests. Thresholds come from the findings in FINDINGS.md.
"""
import numpy as np
import pandas as pd

TIGHT = 0.85             # utilization above which prices have historically jumped
TIGHTENING = 0.75        # watch zone
RISING_PP = 3.0          # 4-week rise in utilization (percentage points) that counts as "rising"
SUPPLY_LEAD_MONTHS = 9   # construction growth -> utilization lag (one cycle observed; see FINDINGS.md)


def _upto(df, asof):
    return df.loc[:pd.Timestamp(asof)]


def _pct(a, b):
    return float(100 * (a / b - 1)) if pd.notna(a) and pd.notna(b) and b else np.nan


def scarcity(prices: pd.DataFrame, util: pd.DataFrame, asof) -> pd.DataFrame:
    """Per GPU: how full the market is and what the price is doing.

    Utilization is averaged over 7 days so the weekday cycle (peak Wed-Thu, low at weekends)
    doesn't make Thursdays look tight and Sundays look loose.
    """
    p, u = _upto(prices, asof).ffill(), _upto(util, asof)
    u7 = u.rolling(7, min_periods=4).mean()
    rows = {}
    for g in prices.columns:
        if p[g].dropna().empty or u7[g].dropna().empty:
            continue
        now, wk, mo = u7[g].iloc[-1], u7[g].shift(7).iloc[-1], u7[g].shift(28).iloc[-1]
        change_4w = 100 * (now - mo) if pd.notna(mo) else np.nan
        if now >= TIGHT:
            status = "tight"
        elif now >= TIGHTENING and change_4w >= RISING_PP:
            status = "tightening"
        elif now >= TIGHTENING:
            status = "watch"
        else:
            status = "slack"
        above = u7[g] >= TIGHT
        streak = 0
        for v in above.iloc[::-1]:
            if not v:
                break
            streak += 1
        price = p[g].iloc[-1]
        rows[g] = {
            "price": round(float(price), 3),
            "price_7d_%": round(_pct(price, p[g].shift(7).iloc[-1]), 1),
            "price_30d_%": round(_pct(price, p[g].shift(30).iloc[-1]), 1),
            "util_7d": round(float(now), 3),
            "spare_capacity_%": round(100 * (1 - float(now)), 1),
            "util_change_1w_pp": round(100 * (now - wk), 1) if pd.notna(wk) else np.nan,
            "util_change_4w_pp": round(change_4w, 1),
            "days_above_85%": streak,
            "status": status,
            "last_price_date": p[g].dropna().index.max().date().isoformat(),
            "last_util_date": u[g].dropna().index.max().date().isoformat(),
        }
    return pd.DataFrame(rows).T


def supply_pipeline(construction: pd.Series, asof) -> dict:
    """US data-center construction spending (Census): latest level and growth.

    Census publishes each month's figure around the first business day two months later
    (August data on ~1 October), so only months published by `asof` are used. This keeps
    --asof runs honest. Faster growth has historically been followed by looser
    utilization ~9 months later.
    """
    c = construction.dropna()
    c = c[c.index + pd.DateOffset(months=2) <= pd.Timestamp(asof)]
    if len(c) < 16:
        return {}
    growth = 100 * c.pct_change(12)
    latest = c.index[-1]
    g_now, g_3m = growth.iloc[-1], growth.iloc[-4]
    direction = "accelerating" if g_now - g_3m > 5 else "slowing" if g_now - g_3m < -5 else "steady"
    implication = {"accelerating": "a looser market", "slowing": "a tighter market",
                   "steady": "no change in how tight the market is"}[direction]
    effect_month = latest + pd.DateOffset(months=SUPPLY_LEAD_MONTHS)
    return {
        "latest_month": latest.strftime("%Y-%m"),
        "spending_bn_annual_rate": round(float(c.iloc[-1]) / 1000, 1),
        "growth_yoy_%": round(float(g_now), 1),
        "growth_yoy_3m_ago_%": round(float(g_3m), 1),
        "direction": direction,
        "points_to": f"{implication} around {effect_month:%B %Y}",
        "effect_month": effect_month.strftime("%B %Y"),
    }


def memory(prices: pd.DataFrame, memory_prices: pd.DataFrame, asof) -> dict:
    """Memory premium (same chip, more memory) and Ornn memory spot prices.

    Changes are measured against the value on the calendar date 30 / 90 / 365 days earlier
    (the latest value on or before it), so gaps in a series don't stretch the window.
    """
    def back(s: pd.Series, days: int):
        return s.asof(s.index[-1] - pd.Timedelta(days=days))

    p = _upto(prices, asof).ffill()
    out = {}
    for name, hi, lo in [("H200/H100", "H200", "H100 SXM"), ("RTXPRO6000/RTX5090", "RTX PRO 6000 WS", "RTX 5090")]:
        if hi in p and lo in p:
            ratio = (p[hi] / p[lo]).rolling(14, min_periods=7).mean().dropna()
            if len(ratio) > 90:
                out[f"premium_{name}"] = round(float(ratio.iloc[-1]), 2)
                out[f"premium_{name}_90d_change_%"] = round(_pct(ratio.iloc[-1], back(ratio, 90)), 1)
    spot = {}
    for name in memory_prices.columns:
        s = memory_prices[name].loc[:pd.Timestamp(asof)].dropna()
        if len(s) < 2:
            continue
        spot[name] = {"price": round(float(s.iloc[-1]), 2),
                      "change_30d_%": round(_pct(s.iloc[-1], back(s, 30)), 1),
                      "change_90d_%": round(_pct(s.iloc[-1], back(s, 90)), 1),
                      "change_1y_%": round(_pct(s.iloc[-1], back(s, 365)), 1),
                      "last_date": s.index[-1].date().isoformat()}
    out["spot"] = spot
    return out


def energy_watch(price: pd.Series, drivers: pd.DataFrame, asof, weeks: int = 104,
                 lags=range(0, 13), shuffles: int = 300) -> pd.DataFrame:
    """Rolling check for whether oil/gas lead the GPU price (weekly % changes, last `weeks` weeks).

    For each driver: the strongest lagged correlation, how often randomly slid copies of the
    driver reach that strength at any lag, and the same correlation in each half of the window
    separately. A lasting relationship should show up in both halves; shocks like the 2026
    Hormuz closure produce a strong correlation that lives in one half only.
    Verdicts: "no signal" (could be chance), "one period only" (beats chance, but only in one
    half), "possible signal - check" (beats chance and holds in both halves with the same sign).
    """
    w = pd.concat([price.rename("y"), drivers], axis=1).loc[:pd.Timestamp(asof)].ffill()
    w = w.resample("W-FRI").last().pct_change(fill_method=None).iloc[-weeks:] * 100
    y = w["y"]
    band = 2 / np.sqrt(max(y.count(), 1))
    rng = np.random.default_rng(0)
    rows = {}
    for d in drivers.columns:
        x = w[d]
        corrs = pd.Series({k: y.corr(x.shift(k)) for k in lags})
        if corrs.isna().all():
            continue
        best = int(corrs.abs().idxmax())
        pair = pd.concat([x.shift(best), y], axis=1).dropna()
        half = len(pair) // 2
        first, second = (pair.iloc[:half].corr().iloc[0, 1], pair.iloc[half:].corr().iloc[0, 1])
        half_band = 2 / np.sqrt(max(half, 1))
        xv = x.dropna()
        hits = 0
        for _ in range(shuffles):
            slid = pd.Series(np.roll(xv.values, rng.integers(5, len(xv) - 5)), xv.index).reindex(y.index)
            hits += max(abs(y.corr(slid.shift(k))) for k in lags) >= abs(corrs[best])
        chance = 100 * hits / shuffles
        both = all(abs(c) > half_band and np.sign(c) == np.sign(corrs[best]) for c in (first, second))
        verdict = "no signal" if chance >= 5 else "possible signal - check" if both else "one period only"
        rows[d] = {"best_lag_weeks": best, "corr": round(float(corrs[best]), 2),
                   "corr_first_half": round(float(first), 2), "corr_second_half": round(float(second), 2),
                   "chance_any_lag_%": round(chance, 1), "noise_band": round(band, 2), "verdict": verdict}
    return pd.DataFrame(rows).T


def data_quality(prices: pd.DataFrame, util: pd.DataFrame, asof, jump_pct: float = 15,
                 stale_days: int = 3, lookback_days: int = 30) -> list[str]:
    """Warnings a human should look at before trusting today's numbers."""
    asof = pd.Timestamp(asof)
    issues = []
    for name, df in [("price", prices), ("utilization", util)]:
        for g in df.columns:
            last = df[g].loc[:asof].dropna().index.max()
            if pd.notna(last) and (asof - last).days > stale_days:   # NaT = not listed yet, not stale
                issues.append(f"{g}: no new {name} data since {last:%d %b %Y}")
    # Large price moves that utilization doesn't explain. Listed for a human to review, not
    # labelled automatically: the two known index artifacts (Aug 2024, Dec 2025) looked like this,
    # but so do some genuine moves in a tight market, where small utilization changes move prices a lot.
    p = prices.loc[:asof].ffill()
    u7 = util.loc[:asof].rolling(7, min_periods=4).mean()
    since = asof - pd.Timedelta(days=lookback_days)
    for g in prices.columns:
        move3 = (100 * (p[g] / p[g].shift(3) - 1)).loc[since:]
        big = move3[move3.abs() >= jump_pct]
        if big.empty:
            continue
        episodes = (big.index.to_series().diff() > pd.Timedelta(days=1)).cumsum()
        for _, days in big.groupby(episodes.values):
            day = days.abs().idxmax()
            move = days[day]
            util_move = 100 * (u7[g].asof(day) - u7[g].asof(day - pd.Timedelta(days=7)))
            if pd.notna(util_move) and util_move * move > 0 and abs(util_move) >= 3:
                continue   # utilization moved the same way: consistent with a scarcity move
            start = p[g].asof(day - pd.Timedelta(days=3))
            later = p[g].loc[day + pd.Timedelta(days=1):day + pd.Timedelta(days=14)]
            if later.empty or (asof - day).days < 3:
                status = "Too recent to tell if it holds"
            elif ((later / start - 1).abs() < 0.05).any():
                status = "It has since reversed"
            else:
                status = "It has held so far"
            issues.append(f"{g}: price {move:+.0f}% in 3 days (to {day.day} {day:%b}) while utilization moved "
                          f"{util_move:+.1f} points. {status}.")
    return issues
