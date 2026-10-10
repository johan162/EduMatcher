"""Sectors for ``pm-market-sim --init``: who belongs where, and how a
typical member of each sector moves.

The membership table covers the tickers of the bundled examples (the s150
set and the 150 that ``s300-load`` adds), following the usual GICS sectors.
A ticker it does not know is spread over the sectors in a fixed order, so a
generated file is the same every time.
"""

from __future__ import annotations

from typing import NamedTuple


class SectorProfile(NamedTuple):
    vol: float  # annual
    beta_market: float
    beta_sector: float


PROFILES: dict[str, SectorProfile] = {
    "TECH": SectorProfile(0.35, 0.60, 0.45),
    "COMMUNICATION": SectorProfile(0.30, 0.55, 0.35),
    "CONSUMER_DISC": SectorProfile(0.33, 0.55, 0.40),
    "CONSUMER_STAPLES": SectorProfile(0.18, 0.40, 0.40),
    "ENERGY": SectorProfile(0.35, 0.45, 0.60),
    "FINANCIALS": SectorProfile(0.27, 0.60, 0.45),
    "HEALTHCARE": SectorProfile(0.25, 0.45, 0.40),
    "INDUSTRIALS": SectorProfile(0.26, 0.60, 0.40),
    "MATERIALS": SectorProfile(0.30, 0.50, 0.45),
    "UTILITIES": SectorProfile(0.18, 0.35, 0.60),
    "REAL_ESTATE": SectorProfile(0.25, 0.50, 0.50),
}

_MEMBERS = {
    "TECH": "AAPL ACN ADBE ADI ADSK AMAT AMD ANET APH ASML AVGO CDNS CDW CRM CRWD "
    "CSCO CTSH DDOG ENPH EPAM FICO FSLR FTNT GLW HPE HPQ IBM INTC INTU IT KLAC "
    "LRCX MCHP MDB MSFT MSI MU NET NOW NVDA ORCL PANW PLTR QCOM SAP SHOP SNOW "
    "SONY TEAM TSM TXN ZS",
    "COMMUNICATION": "CHTR CMCSA DIS EA GOOGL META NFLX ROKU SPOT T TMUS VZ",
    "CONSUMER_DISC": "ABNB AMZN AZO BABA BBY BKNG CCL CMG DHI DPZ DRI EBAY EXPE F "
    "GM GPC GRMN HAS HD HLT HMC LCID LEN LOW LULU LVS MAR MCD MGM NKE RCL RIVN "
    "SBUX TM TSLA UBER",
    "CONSUMER_STAPLES": "CHD CL CLX COST DG DLTR EL GIS HSY K KDP KHC KMB KO KR MDLZ "
    "MKC MNST MO PEP PG TGT WMT",
    "ENERGY": "BKR COP CVX DVN EOG FANG HAL HES KMI MPC NOV OXY PSX SLB VLO XOM",
    "FINANCIALS": "AFL AIG AJG ALL AMP AON AXP BAC BK BLK BRO BX C CB CINF CME COF "
    "FI FIS FITB GPN GS HBAN HIG JPM KEY MA MCO MET MMC MS MSCI MTB NDAQ PYPL "
    "SCHW SQ V WFC",
    "HEALTHCARE": "ABBV AMGN BAX BDX BIIB BMY BSX CAH CI CNC CVS DHR DXCM EW GEHC "
    "GILD HCA HUM IDXX ILMN INCY IQV ISRG JNJ LH LLY MCK MDT MRK MRNA MTD PFE UNH",
    "INDUSTRIALS": "AAL AME BA BR CARR CAT CMI CPRT CSX CTAS DAL DE DOV EFX EMR ETN "
    "EXPD FAST FDX GD GE GWW HON HUBB IR ITW JBHT JCI LHX LMT MMM NOC NSC PAYX ADP "
    "RTX UAL UNP UPS",
    "MATERIALS": "ALB APD CF CTVA DD DOW ECL FCX IFF IP LIN LYB MLM MOS NEM NUE SHW",
    "UTILITIES": "AEP ATO AWK CEG CMS D DTE DUK ED EIX ES ETR EXC NEE NRG SO SRE XEL",
    "REAL_ESTATE": "AMT ARE AVB CCI CSGP DLR EQIX IRM MAA O PLD PSA REG SPG WELL",
}

SECTOR_OF: dict[str, str] = {
    ticker: sector for sector, members in _MEMBERS.items() for ticker in members.split()
}


def sector_for(ticker: str, unknown_index: int) -> str:
    """The ticker's sector; an unknown ticker gets the ``unknown_index``-th
    sector in turn."""
    known = SECTOR_OF.get(ticker.upper())
    if known is not None:
        return known
    names = sorted(PROFILES)
    return names[unknown_index % len(names)]
