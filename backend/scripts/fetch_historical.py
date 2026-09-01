"""
Fetch real daily OHLCV history for Velure's 15-asset universe via yfinance
and write it in the format the replay/backtest engine expects:

    backend/data/historical/<INTERNAL_TICKER>.csv
    date,open,high,low,close,volume

This powers BOTH:
  · training IF/LSTM on real calm-market data (scripts/train_on_real.py)
  · the labeled-crisis backtest (backtesting/harness.py)

Usage:
    python scripts/fetch_historical.py [--start 2007-01-01]

No API key required. Crypto/FX simply start later / carry 0 volume; the
replay engine only uses the close price, so that's fine.
"""
import argparse
import csv
from datetime import date
from pathlib import Path

import yfinance as yf

# internal name -> Yahoo Finance symbol
SYMBOL_MAP = {
    # US banks
    "JPM": "JPM", "GS": "GS", "BAC": "BAC", "C": "C", "MS": "MS",
    # equity index / sector ETFs
    "SPY": "SPY", "QQQ": "QQQ", "DIA": "DIA", "IWM": "IWM", "XLF": "XLF",
    # FX (Yahoo uses the =X suffix; USDJPY=X is JPY per 1 USD)
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    # crypto
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
}

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"


def fetch_one(internal: str, symbol: str, start: str, end: str) -> int:
    """Fetch one ticker and write its CSV. Returns row count."""
    df = yf.Ticker(symbol).history(
        start=start, end=end, interval="1d", auto_adjust=False
    )
    if df is None or len(df) == 0:
        print(f"  {internal:8s} ({symbol:10s}) — NO DATA")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{internal}.csv"
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for idx, row in df.iterrows():
            close = row.get("Close")
            if close is None or close != close or close <= 0:  # NaN / non-positive guard
                continue
            w.writerow([
                idx.strftime("%Y-%m-%d"),
                round(float(row.get("Open", close)), 6),
                round(float(row.get("High", close)), 6),
                round(float(row.get("Low", close)), 6),
                round(float(close), 6),
                int(row.get("Volume", 0) or 0),
            ])
            n += 1
    first = df.index[0].strftime("%Y-%m-%d")
    last = df.index[-1].strftime("%Y-%m-%d")
    print(f"  {internal:8s} ({symbol:10s}) — {n:5d} rows  {first} → {last}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2007-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    args = ap.parse_args()

    print(f"Fetching {len(SYMBOL_MAP)} tickers  {args.start} → {args.end}")
    print(f"Output: {OUT_DIR}")
    total = 0
    for internal, symbol in SYMBOL_MAP.items():
        try:
            total += fetch_one(internal, symbol, args.start, args.end)
        except Exception as e:
            print(f"  {internal:8s} ({symbol:10s}) — ERROR: {e}")
    print(f"Done. {total} total rows written.")


if __name__ == "__main__":
    main()
