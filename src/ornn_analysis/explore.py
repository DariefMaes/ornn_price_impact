"""Small helpers for looking at the data. No models: just changes, correlations and dates."""
import numpy as np
import pandas as pd

from .data import LOADERS, load_ornn, load_ornn_utilization
from .config import EVENTS_FILE
from .series import DRIVERS, GPUS


def load_gpus(gpus: list[str] = GPUS) -> pd.DataFrame:
    """One column per GPU, daily $/hour."""
    return pd.DataFrame({g: load_ornn(g) for g in gpus})


def load_utilization(gpus: list[str] = GPUS) -> pd.DataFrame:
    """One column per GPU, daily share of Ornn's tracked capacity that is rented (0 to 1)."""
    return pd.DataFrame({g: load_ornn_utilization(g) for g in gpus})


def first_crossing(s: pd.Series, level: float, after=None):
    """First date the series is at or above `level` (optionally only looking after a date)."""
    s = s.loc[pd.Timestamp(after):] if after is not None else s
    hits = s[s >= level].index
    return hits.min() if len(hits) else pd.NaT


def utilization_timing(prices: pd.DataFrame, util: pd.DataFrame, util_level: float = 0.85,
                       price_rise: float = 0.30, base=("2026-01-01", "2026-02-15"), after="2026-01-15") -> pd.DataFrame:
    """For each GPU: when did utilization (14-day average) first reach `util_level`, and when did
    the price first reach `price_rise` above its level in the `base` period? Positive gap = utilization first."""
    smooth = util.rolling(14, min_periods=7).mean()
    rows = {}
    for g in prices.columns:
        base_price = prices[g].loc[base[0]:base[1]].mean()
        t_util = first_crossing(smooth[g], util_level, after)
        t_price = first_crossing(prices[g] / base_price, 1 + price_rise, after)
        rows[g] = {f"util_reached_{int(util_level * 100)}%": t_util.date() if pd.notna(t_util) else None,
                   f"price_up_{int(price_rise * 100)}%": t_price.date() if pd.notna(t_price) else None,
                   "days_util_first": (t_price - t_util).days if pd.notna(t_util) and pd.notna(t_price) else None}
    return pd.DataFrame(rows).T


def load_drivers(drivers: dict = DRIVERS) -> pd.DataFrame:
    """One column per driver, daily. Anything that fails to load is skipped with a note."""
    out = {}
    for name, (source, sid, _group, _why) in drivers.items():
        try:
            out[name] = LOADERS[source](sid)
        except Exception as exc:  # noqa: BLE001 - keep going if one source is down or needs a key
            print(f"skipped {name}: {type(exc).__name__}: {str(exc)[:80]}")
    return pd.DataFrame(out)


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Friday-close value of each week."""
    return df.resample("W-FRI").last()


def pct_change(df: pd.DataFrame) -> pd.DataFrame:
    """Week-on-week % change. Comparing changes rather than levels avoids
    finding a link just because two series both trended over the period."""
    return weekly(df).pct_change(fill_method=None) * 100


def rebase(df: pd.DataFrame, start=None) -> pd.DataFrame:
    """Each series = 100 at the start date, so different units fit on one chart."""
    df = df.ffill().loc[start:] if start is not None else df.ffill()
    return 100 * df / df.bfill().iloc[0]


def lag_correlations(target: pd.Series, others: pd.DataFrame, lags=range(-8, 13)) -> pd.DataFrame:
    """Correlation between each series' weekly change and the target's weekly change k weeks later.

    Positive lag k: the other series moved k weeks BEFORE the target (it leads).
    Negative lag:   the target moved first.
    Lag 0:          same week.
    """
    return pd.DataFrame({k: others.shift(k).corrwith(target) for k in lags})


def chance_test(target: pd.Series, other: pd.Series, lag: int, lags=range(-8, 13), n: int = 2000) -> dict:
    """How often would a correlation this strong appear by luck?

    Slides `other` to a random start date (wrapping around) many times, which keeps
    its own ups and downs but breaks any real timing link with the target, and
    counts how often the shuffled version matches the real correlation.
    `any_lag` is the fair number when the lag was picked after looking at a chart.
    """
    real = target.corr(other.shift(lag))
    values = other.dropna()
    rng = np.random.default_rng(0)
    at_lag = at_any = 0
    for _ in range(n):
        slid = pd.Series(np.roll(values.values, rng.integers(10, len(values) - 10)), values.index)
        corrs = np.array([abs(target.corr(slid.shift(k))) for k in lags])
        at_lag += abs(target.corr(slid.shift(lag))) >= abs(real)
        at_any += corrs.max() >= abs(real)
    return {"corr": round(real, 2), "chance_at_this_lag_%": round(100 * at_lag / n, 1),
            "chance_at_any_lag_%": round(100 * at_any / n, 1)}


def week_contributions(target: pd.Series, other: pd.Series, lag: int, top: int = 5) -> pd.DataFrame:
    """Which weeks make up the correlation. If one week dominates, it's one event, not a pattern.

    Each week's contribution is the product of its two standardized values divided by (n - 1);
    the contributions add up exactly to the correlation. Weeks are ranked by how much they push
    the correlation in its own direction (most positive first for a positive correlation, most
    negative first for a negative one)."""
    pair = pd.concat([other.shift(lag).rename(f"other_{lag}w_earlier_%"), target.rename("target_%")], axis=1).dropna()
    z = (pair - pair.mean()) / pair.std()
    contrib = (z.prod(axis=1) / (len(z) - 1)).rename("adds_to_corr")
    direction = np.sign(contrib.sum()) or 1
    share = contrib.loc[(direction * contrib).sort_values(ascending=False).index]
    out = pd.concat([share, pair], axis=1, sort=False).loc[share.index].head(top).round(2)
    out.attrs["without_top_week"] = round(pair.drop(share.index[0]).corr().iloc[0, 1], 2)
    return out


def noise_band(n_weeks: int) -> float:
    """Rough size of a correlation you'd get by pure chance (95%)."""
    return 2 / np.sqrt(n_weeks)


def biggest_moves(s: pd.Series, n: int = 8) -> pd.DataFrame:
    """The weeks with the largest % moves in a series."""
    chg = pct_change(s.to_frame()).iloc[:, 0].dropna()
    top = chg.reindex(chg.abs().nlargest(n).index)
    return pd.DataFrame({"week_ending": top.index.date, "change_%": top.round(1).values,
                         "price_after": weekly(s.to_frame()).iloc[:, 0].reindex(top.index).round(2).values})


def what_else_moved(changes: pd.DataFrame, week, weeks_before: int = 2) -> pd.DataFrame:
    """% change of every series in the given week and the weeks just before it."""
    week = pd.Timestamp(week)
    rows = changes.loc[week - pd.Timedelta(weeks=weeks_before):week]
    rows.index = [f"{d.date()}" for d in rows.index]
    return rows.T.round(1)


def find_episodes(s: pd.Series, window: int = 14, threshold: float = 15) -> pd.DataFrame:
    """Big moves: periods where the price changed more than `threshold` % within `window` days.

    For each episode:
      start / peak     trough-to-peak (or peak-to-trough) dates of the move
      move_%           size of the move
      days             how long it took
      biggest_day_%    share of the move that happened on a single day. High = a sudden step
                       (one repricing or listing change), low = a gradual climb (demand building)
      after_30d_%      where the price was 30 days after the peak, vs the start.
                       Near 0 = the move fully reversed (a spike, or possibly a data glitch)
    """
    s = s.dropna().asfreq("D").ffill()
    chg = (s / s.shift(window) - 1) * 100
    flagged = chg[chg.abs() >= threshold].index.to_series()
    if flagged.empty:
        return pd.DataFrame()
    rows = []
    for _, days in flagged.groupby((flagged.diff() > pd.Timedelta(days=window)).cumsum()):
        seg = s.loc[days.iloc[0] - pd.Timedelta(days=window):days.iloc[-1]]
        up = chg.loc[days].mean() > 0
        peak = seg.idxmax() if up else seg.idxmin()
        before = seg.loc[:peak]
        start = before.idxmin() if up else before.idxmax()
        move = s[peak] / s[start] - 1
        daily = s.loc[start:peak].diff().abs()
        later = s.loc[:peak + pd.Timedelta(days=30)].iloc[-1]
        rows.append({
            "start": start.date(), "peak": peak.date(), "days": (peak - start).days,
            "from_$": round(s[start], 2), "to_$": round(s[peak], 2), "move_%": round(100 * move, 1),
            "biggest_day_%": round(100 * daily.max() / abs(s[peak] - s[start]), 0) if s[peak] != s[start] else None,
            "after_30d_%": round(100 * (later / s[start] - 1), 1),
        })
    return pd.DataFrame(rows)


def all_episodes(gpus: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """find_episodes for every GPU, in date order."""
    out = [find_episodes(gpus[g], **kwargs).assign(gpu=g) for g in gpus]
    df = pd.concat([o for o in out if not o.empty], ignore_index=True)
    return df[["gpu", *df.columns.drop("gpu")]].sort_values("start", ignore_index=True)


def load_events() -> pd.DataFrame:
    """Hand-curated news timeline from data/events.csv (date, event, category, source)."""
    return pd.read_csv(EVENTS_FILE, parse_dates=["date"])


def plot_window(df: pd.DataFrame, start, end, events: pd.DataFrame | None = None, title: str = ""):
    """Series rebased to 100 at `start`, with news events marked as vertical lines."""
    ax = rebase(df.loc[:pd.Timestamp(end)], start).plot(figsize=(12, 5), lw=1.3, title=title)
    ax.axhline(100, color="grey", lw=0.5)
    if events is not None:
        shown = events[(events["date"] >= pd.Timestamp(start)) & (events["date"] <= pd.Timestamp(end))]
        for i, (_, ev) in enumerate(shown.iterrows()):
            ax.axvline(ev["date"], color="grey", ls="--", lw=0.8)
            ax.annotate(ev["event"], (ev["date"], 1 - 0.05 * (i % 6)), xycoords=("data", "axes fraction"),
                        fontsize=7, rotation=0, ha="left", va="top", color="dimgrey")
    ax.legend(fontsize=8, loc="center left")
    return ax


def change_over(df: pd.DataFrame, start, end) -> pd.Series:
    """% change of every column between two dates (last known value on each date)."""
    filled = df.ffill()
    return (100 * (filled.loc[:pd.Timestamp(end)].iloc[-1] / filled.loc[:pd.Timestamp(start)].iloc[-1] - 1)).round(1)
