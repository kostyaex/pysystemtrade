"""
Refresh the on-disk CSV cache (data/futures/bybit/) from MongoDB.

Reads every ByBit instrument from the production MongoDB (bybit_ohlcv and
bybit_funding collections) and writes CSV files that the offline backtest
reads via ``bybitFuturesSimData(data_source='api')`` with use_cache=True.

Run on the PROD server after the regular dagu update has written fresh data
into MongoDB.  No ByBit API calls are made.

Usage:
    python -m sysinit.futures.bybit.export_bybit_cache_from_mongo
    python -m sysinit.futures.bybit.export_bybit_cache_from_mongo --instruments BTC_BYBIT ETH_BYBIT
"""

import argparse
import os
import sys

import pandas as pd

from sysdata.mongodb.mongo_bybit_data import (
    mongoBybitOHLCVData,
    mongoBybitFundingData,
    BYBIT_DATABASE_NAME,
)
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData

_OHLCV_CACHE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "futures", "bybit", "ohlcv"
)
_FUNDING_CACHE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "futures", "bybit", "funding"
)

_DATE_FMT = "%Y-%m-%d"
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_OHLCV_COLUMNS = ["DATETIME", "OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]
_FUNDING_COLUMNS = ["DATETIME", "fundingRate"]


def _instrument_to_cache_name(instrument_code: str) -> str:
    """BTC_BYBIT -> btc, SOL_BYBIT -> sol."""
    base = instrument_code.replace("_BYBIT", "")
    return base.lower()


def _export_ohlcv(instrument_code: str, mongo_ohlcv: mongoBybitOHLCVData) -> bool:
    cache_name = _instrument_to_cache_name(instrument_code)
    path = os.path.join(_OHLCV_CACHE_DIR, cache_name + ".csv")

    df = mongo_ohlcv.get_ohlcv(instrument_code)
    if df.empty:
        print(f"  {instrument_code}: no OHLCV data in mongo, skipping")
        return False

    # MongoDB stores full datetime; daily candles are midnight.
    # Strip the time portion to match the CSV cache convention.
    df.index = pd.DatetimeIndex([dt.strftime(_DATE_FMT) for dt in df.index])
    df.index.name = "DATETIME"
    df = df[_OHLCV_COLUMNS[1:]]  # drop DATETIME col (it's the index)

    df.to_csv(path, index=True)
    print(f"  {instrument_code}: wrote {len(df)} rows to {path}")
    return True


def _export_funding(instrument_code: str, mongo_funding: mongoBybitFundingData) -> bool:
    cache_name = _instrument_to_cache_name(instrument_code)
    path = os.path.join(_FUNDING_CACHE_DIR, cache_name + ".csv")

    df = mongo_funding.get_funding(instrument_code)
    if df.empty:
        print(f"  {instrument_code}: no funding data in mongo, skipping")
        return False

    df.index = pd.DatetimeIndex([dt.strftime(_DATETIME_FMT) for dt in df.index])
    df.index.name = "DATETIME"
    df = df[["fundingRate"]]

    df.to_csv(path, index=True)
    print(f"  {instrument_code}: wrote {len(df)} rows to {path}")
    return True


def export_bybit_cache(instruments: list | None = None):
    os.makedirs(_OHLCV_CACHE_DIR, exist_ok=True)
    os.makedirs(_FUNDING_CACHE_DIR, exist_ok=True)

    mongo_ohlcv = mongoBybitOHLCVData()
    mongo_funding = mongoBybitFundingData()

    if instruments is None:
        all_instruments = mongo_ohlcv.get_list_of_instruments()
        # Only ByBit instruments (end with _BYBIT)
        instruments = [i for i in all_instruments if i.endswith("_BYBIT")]

    if not instruments:
        print("No ByBit instruments found in MongoDB.")
        return

    print(f"Exporting {len(instruments)} instrument(s) from MongoDB to CSV cache...")

    ok, fail = 0, 0
    for instrument_code in sorted(instruments):
        try:
            ohlcv_ok = _export_ohlcv(instrument_code, mongo_ohlcv)
            funding_ok = _export_funding(instrument_code, mongo_funding)
            if ohlcv_ok or funding_ok:
                ok += 1
            else:
                print(f"  WARNING: {instrument_code} had no data in either collection")
                fail += 1
        except Exception as e:
            print(f"  ERROR exporting {instrument_code}: {e}", file=sys.stderr)
            fail += 1

    print(f"\nDone. Exported: {ok}, errors/empty: {fail}")


def main():
    parser = argparse.ArgumentParser(
        description="Refresh bybit CSV cache from MongoDB (no API calls)."
    )
    parser.add_argument(
        "--instruments",
        nargs="+",
        default=None,
        help="Specific instrument codes to export (default: all _BYBIT instruments in mongo)",
    )
    args = parser.parse_args()
    export_bybit_cache(instruments=args.instruments)


if __name__ == "__main__":
    main()
