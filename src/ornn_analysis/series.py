"""What we look at. Add or remove a line here to change the analysis.

GPU prices and utilization come from Ornn, data-center construction from Census, everything else
from Yahoo Finance.
"""

# GPUs available from the Ornn API.
GPUS = ["H100 SXM", "H200", "B200", "A100 SXM4", "RTX 5090", "RTX PRO 6000 WS"]

# Ornn memory spot prices used in the daily report: display name -> Ornn memory id.
# Commodity DRAM, not HBM, but it reflects the same shortage (HBM takes DRAM production capacity).
MEMORY = {
    "DDR5 16Gb chip": "mem_ddr5_16gb",
    "DDR5 server module (RDIMM 32GB)": "mem_ddr5_rdimm_32gb",
}

# name: (source, Yahoo ticker, group, why it might matter)
DRIVERS = {
    # Energy: the starting hypothesis
    "henry_hub_gas": ("yahoo", "NG=F", "energy", "Henry Hub gas futures; gas sets most US power prices"),
    "wti_oil":       ("yahoo", "CL=F", "energy", "WTI crude futures (US)"),
    "brent_oil":     ("yahoo", "BZ=F", "energy", "Brent crude futures (global)"),
    # Demand: how much people want AI compute
    "nvidia":        ("yahoo", "NVDA", "demand", "Market view of AI demand"),
    "coreweave":     ("yahoo", "CRWV", "demand", "GPU cloud provider (listed Mar 2025)"),
    "semis_index":   ("yahoo", "^SOX", "demand", "Semiconductor stocks"),
    # Hardware supply
    "micron":        ("yahoo", "MU", "supply", "GPU memory (HBM) maker"),
    "sk_hynix":      ("yahoo", "000660.KS", "supply", "Main HBM supplier to Nvidia"),
    "samsung":       ("yahoo", "005930.KS", "supply", "Largest DRAM maker"),
    # Financing: GPUs are mostly bought with borrowed money (yields are in %, e.g. 4.2 = 4.2%)
    "tbill_3m":      ("yahoo", "^IRX", "financing", "13-week T-bill yield; tracks SOFR, the base rate GPU-backed loans float on"),
    "treasury_10y":  ("yahoo", "^TNX", "financing", "10-year Treasury yield"),
    "hy_bonds":      ("yahoo", "HYG", "financing", "High-yield bond ETF; falls when risky borrowing gets more expensive"),
    # General market mood
    "vix":           ("yahoo", "^VIX", "market", "Market fear index"),
    # Raw materials: should NOT matter (a few dollars of a ~$30k GPU), useful as a sanity check
    "copper":        ("yahoo", "HG=F", "raw materials", "Sanity check"),
    "gold":          ("yahoo", "GC=F", "raw materials", "Sanity check"),
}
