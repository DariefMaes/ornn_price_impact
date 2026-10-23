# Findings

The primary driving factor of GPU pricing seems to be scarcity, not energy prices. Looking at the correlation between oil/gas and GPU prices, I couldn't find a reliable correlation figure that was consistent across the full Ornn data horizon. In 2026 two separate events happened close together, the oil shock from the Strait of Hormuz closure and a GPU squeeze, which creates some correlation, but not a consistent pattern.

The physical world seems to matter more through how much capacity gets built. Here, we notice that data-center construction and memory supply have a clearer link to GPU prices.

**NOTE**: every positive finding rests on essentially one cycle: a slowdown in 2025, a squeeze in spring 2026, a
dip in June and a recovery.

## What moves prices

| #   | Finding                                                                                                                  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Prices respond to scarcity, non-linearly.** Flat until utilization passes ~85%, then sharply up.                       | In 2026, utilization reached 85% before the price rose 30% for **6 of 6 GPUs** (6-99 days earlier). The link held up (spring), down (June) and up again (July). The H100 near-doubling ($1.77 to $3.14, mid-April to mid-May) happened as spare capacity fell from ~12% to ~3%.                                                                                                                         |
| 2   | **Data-center construction leads utilization by ~9 months.** Slower construction growth is followed by a tighter market. | Census construction growth vs utilization 9 months later: −0.71 (H100+A100); −0.47 to −0.81 per GPU at 6-9 months, all negative. A link this strong appears by chance in only 0.7% of random shifts, but it rests on one cycle: without 2026 the correlation is −0.16.                                                                                                                                                           |
| 3   | **The memory (HBM/DRAM) shortage fits the timing and the cross-section.**                                                | Ornn's DDR5 spot price was flat at ~$5 through September 2025, then rose 64% in October and 113% in November, the months H100 utilization began climbing. It is now ~$61 (+442% in a year). The H200/H100 price ratio (same chip, more memory) rose from ~1.3 to ~2.0, about six months after DRAM prices took off (notebook section 10, daily report). Week-to-week DDR5 moves don't lead GPU prices: memory acts slowly, through how much capacity can be built. DDR5 is commodity DRAM rather than the HBM on GPUs, but it reflects the same shortage. In both same-chip pairs the higher-memory GPU rose more since autumn 2025 (H200 +92% vs H100 +44%; RTX PRO 6000 +33% vs RTX 5090 +23%). |
| 4   | **Demand has a workweek cycle.**                                                                                         | Utilization peaks Wed-Thu (+1.5 to +2.4pp vs the 7-day average) and drops at weekends (−2.5 to −3.7pp) for all 6 GPUs (p < 0.001). Prices follow weakly: under 2% peak to trough, peaking Thu-Fri; not significant for H100.                                                                                                                                                                            |

## What doesn't (no detectable lead)

| Input                       | Tested                                                                           | Result                                                                                                                                                                                                                                                                                                                |
| --------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Electricity / gas / oil** | weekly (0-12 weeks)                                                              | Weekly WTI vs H100: 0.07. The 9-week lag (0.31) comes from **one episode**: the oil spike when the Strait of Hormuz closed (March 2026) followed by the H100 squeeze (May-June). Without March-June 2026, the correlation is 0.11. Other GPUs don't show it, thus showing this hypothesis is not consistent across GPUs. |
| **Interest rates**          | 13-week T-bill (tracks SOFR), 10-year Treasury, high-yield bond ETF, VIX; weekly | Best case: 10-year yield 2 weeks earlier, 0.28 correlation. However, there is a 9% chance at any lag and the event is driven by August 2024 (0.17 correlation without it). T-bill and high-yield bonds: 59-69% chance.                                                                                                |

## Method

Every candidate driver went through the same three steps:

1. **Look for a link.** Compare weekly _changes_ in the driver (time-series we think caused the change) with weekly changes in the GPU price, with the
   driver shifted 0-12 weeks earlier. Using changes rather than price levels avoids false links between any two
   prices that simply trended the same way.
2. **Rule out luck.** Move the driver's history to random dates 2,000 times and count how often a link this
   strong appears by accident, taking the best match at any delay, since the delay was chosen after looking.
   Under 5% passes.
3. **Rule out a one-off.** A real driver should survive removing its biggest week or episode, show up in both
   years of data and for the other GPUs, and be large enough to matter in cents per GPU-hour.

## How trust was established

- **Four checks, not one.** A link only counts if it beats chance, survives removing its biggest week or
  episode, holds for the other GPUs and in both years of data, and is large enough to matter in cents per
  GPU-hour. Oil, interest rates and the semiconductor index each passed one check and failed others, so they
  are reported as no lasting link.
- **No look-ahead.** Every signal uses only data available on that date. Census figures are used only after
  their publication date (about two months after the month they describe). Any past day can be reproduced
  with `--asof`.
- **Data checked before use.** Two jumps in the Ornn H100 index (August 2024, December 2025) reversed within
  days while utilization didn't move, so they look like index artifacts rather than trades. They were what
  produced the only interest-rate "signal". Utilization is used as a 7-day average because daily readings are
  noisy and follow a weekly cycle. The daily report flags any similar move for review.
- **Sources.** Ornn (first-party data), Census (official statistics, revised monthly) and Yahoo Finance
  (market prices). Memory prices are Ornn's own DDR5 spot prices; memory-maker share prices were tried as a
  proxy first, but track actual DRAM prices poorly (weekly correlation 0.16), so they're no longer used.
- **What this can't fix.** 2.3 years of data is essentially one cycle. The positive findings are consistent,
  but not yet repeated; the forecast that the market loosens around Q1-Q2 2027 is the first real test.

## What I would do next

- **The wider tech market.** Check whether broad tech indices (S&P 500 Information Technology, Nasdaq-100) lead GPU
  prices. AI announcements tend to trigger stock rallies, and the companies behind them then need to buy or rent
  GPUs. Nvidia, CoreWeave and the semiconductor index are already in the weekly screen (section 5).
- **News, more systematically.** Build out the news timeline (`data/events.csv`) so that every large price move
  can be matched to what happened at the time.
- **New data-center announcements.** Track announced projects with their planned capacity (MW) and number of
  GPUs. This would measure supply more directly, and earlier, than Census construction spending.
- **Kalshi prediction markets.** Use markets such as the yearly count of new US data centers as a
  forward-looking view of supply, once they have enough trading history.
- **Electricity availability.** The question covers the cost _and availability_ of electricity; only cost
  was tested. Grid connection queues (PJM, ERCOT), power-delivery delays and local moratoria limit how fast new
  capacity comes online, which is the most likely route for electricity to affect GPU prices.
- **Water.** I focused on energy and supply/demand first. Once energy showed no signal, supply looked more
  promising than water, so water wasn't tested. Next step: data-center water use and restrictions (for example
  drought rules in key regions) as another possible limit on new capacity.
- **More cycles.** The main limitation is that 2.3 years of data contains essentially one cycle, which makes it
  hard to tell consistent patterns from one-off events. Running the pipeline over the coming months adds
  evidence, starting with the forecast that the market loosens around Q1-Q2 2027.
