# What moves GPU compute prices?

A daily pipeline that tells us whether and how the physical world is moving GPU rental prices, plus the
research behind it.

**Short answer:** prices are set by scarcity. They stay flat until utilization passes about 85%, then rise
sharply. The physical inputs that matter are the ones that limit how much capacity exists:
data-center construction, which leads utilization by about 9 months, and memory (HBM). Energy prices and
interest rates show no detectable lead. Details, how trust was established and what I'd do next are in [FINDINGS.md](FINDINGS.md).

## Start here: the dashboard

`notebooks/dashboard.ipynb` answers the question for today, for all six GPUs: is the physical world
moving GPU prices, and how? Open it with the "Python (ornn-project)" kernel and choose **Run All**.

Each run downloads any data older than 24 hours, so rerunning it gives an up-to-date view. Two settings
in the first code cell:

- `REFRESH = True`: download everything again (use this after Ornn's 4pm ET publication to get that day's prices)
- `ASOF = "2026-03-06"`: show the dashboard as it looked on a past date, using only data available then

| Section                         | What it shows                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 1. Today at a glance            | Summary, and one row per physical input: what it's doing now, the evidence it moves GPU prices, and which way it's pushing |
| 2. How full is each GPU market? | Per-GPU utilization, status and price pressure; price vs utilization charts                                                |
| 3. Supply                       | Census data-center construction growth against utilization months later                                                    |
| 4. Memory                       | Ornn DDR5 spot prices and the H200/H100 memory premium                                                                     |
| 5. Energy                       | Whether oil or gas prices lead each GPU's price                                                                            |
| 6. Each GPU is its own market   | How closely the six GPUs move together                                                                                     |
| 7. Data quality                 | Price moves to review before trusting the numbers                                                                          |

## Quick start

```bash
uv venv .venv --python 3.12
uv pip install --python .venv -r requirements.txt -e .
cp .env.example .env            # add ORNN_API_KEY (data.ornn.com -> Settings -> API Keys)
.venv/bin/python -m ornn_analysis.daily
```

The pipeline prints a report to the terminal and writes no files. Downloads are cached in `data/cache/`
for 24 hours, so reruns are fast; delete that folder to force fresh data.

To see the report as it would have looked on a past date (only data available then is used):

```bash
.venv/bin/python -m ornn_analysis.daily --asof 2026-05-15
```

To get the same signals as machine-readable JSON (for storing, dashboards or alerts):

```bash
.venv/bin/python -m ornn_analysis.daily --json > signals_$(date +%F).json
```

The JSON is one object per run: `gpus` (per GPU: price, 7-day average utilization, spare capacity, 4-week
change, status), `supply`, `memory`, `energy`, `data_quality_notes` and `source_failures`. Field names are stable
and the object carries a `schema_version`, which changes only if fields are renamed or removed. Storing one
object per day builds a history of the signals, for example to check the 2027 supply forecast.

## Running it on a schedule

The pipeline is a single stateless command, so any scheduler can run it (cron, Airflow, a CI job). Run it once a day after Ornn publishes its index (4pm ET), with `--json` if the output should be stored. It needs
`ORNN_API_KEY` in the environment or in `.env`.

The run is resilient: if Yahoo or Census fails, the rest of the report still prints and the failure is listed
under "Source failures". Only missing Ornn data stops the run (exit code 1).

## Reading the report

The report opens with a short summary, followed by five sections:

| Section                             | What it shows                                                                                             | How to use it                                                                                                                                                                                                                                                                         |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. How full is each GPU market?** | Per GPU: price, 7-day average utilization, spare capacity, 4-week change, status                          | The main signal. **Full** (85%+ used) is where prices have jumped before; **Filling up** (75-85% and up 3+ points in 4 weeks) is the early warning; **Busy** is 75-85%; **Room available** is under 75%. A 7-day average is used because demand peaks mid-week and drops at weekends. |
| **2. Supply pipeline**              | Census data-center construction growth, and what it points to ~9 months ahead                             | Faster construction has been followed by a looser market, slower construction by a tighter one. Observed over one cycle, so treat the date as a forecast to check.                                                                                                                    |
| **3. Memory**                       | Ornn DDR5 spot prices (chip and server module); price ratios of same-chip GPU pairs with different memory | Rising DDR5 prices mean the memory shortage that started in Oct 2025 is still going; a rising GPU ratio means memory scarcity is being priced into GPU rentals. DDR5 is commodity DRAM, not the HBM on GPUs, but reflects the same shortage.                                          |
| **4. Energy check**                 | Whether oil or gas moves before H100 prices (weekly, last two years)                                      | A real link must beat chance and show up in both years. Kept so the conclusion updates itself if that changes.                                                                                                                                                                        |
| **5. Data quality**                 | Large price moves that utilization doesn't explain; feeds that stopped updating                           | Review before using the numbers. Two past jumps (Aug 2024, Dec 2025) looked like index artifacts.                                                                                                                                                                                     |

## Project layout

| Path                           | What                                                                                                                          |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `src/ornn_analysis/daily.py`   | The daily pipeline: load, compute, print the report                                                                           |
| `src/ornn_analysis/signals.py` | Signal logic. Pure functions, each computed "as of" a date (no look-ahead)                                                    |
| `src/ornn_analysis/data.py`    | Loaders for the three sources: Ornn (GPU prices, hourly, utilization, memory), Census, Yahoo. Cached for 24h in `data/cache/` |
| `src/ornn_analysis/series.py`  | Which GPUs and drivers to load. **Add or remove series here.**                                                                |
| `src/ornn_analysis/explore.py` | Helpers for the research notebook                                                                                             |
| `notebooks/explore.ipynb`      | The research: every finding in FINDINGS.md is reproduced in a numbered section                                                |
| `data/events.csv`              | Hand-curated news timeline (with sources), marked on the charts in notebook section 6                                         |

## Data sources

| Source                           | Used for                                                           | Access                  |
| -------------------------------- | ------------------------------------------------------------------ | ----------------------- |
| Ornn Data API                    | GPU price indices (daily, hourly), utilization, memory spot prices | `ORNN_API_KEY`          |
| Census C30 construction spending | Data-center construction                                           | Public spreadsheet      |
| Yahoo Finance                    | Oil and gas futures, interest rates, VIX, stock prices (notebook)  | Public (via `yfinance`) |
