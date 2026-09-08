"""
Update ByBit data into MongoDB for production.

For every ByBit instrument (from the CSV instrument config) this:

- fetches the daily OHLCV history from the ByBit *API* (bypassing the local
  CSV cache via use_cache=False; the cache is afterwards refreshed with the
  merged series so local backtests stay in sync),
- fetches the latest funding rate history (also bypassing the cache),
- upserts the data into MongoDB (database 'bybit', collections bybit_ohlcv
  and bybit_funding) - a plain idempotent upsert per (instrument, datetime),
- reports how many rows were added / are present.

The read side is `bybitFuturesSimData(data_source="mongo")`.

Caching note: the on-disk CSV cache in data/futures/bybit is *only* consulted
when use_cache=True (sim/exploration). This production updater always fetches
a fresh tail from the API, so a stale cache can never hide the latest candles
from production. The CSV cache is then re-written with the merged history.

Usage:
    python -m sysproduction.update_bybit_prices [--instruments BTC_BYBIT ...]
        [--full] [--dry-run]
"""

import datetime
import sys

from syscore.constants import arg_not_supplied
from sysdata.bybit.bybit_api import bybitAPI, BYBIT_HISTORY_START_MS
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from sysdata.mongodb.mongo_bybit_data import (
    mongoBybitOHLCVData,
    mongoBybitFundingData,
)
from syslogging.logger import *
import pandas as pd

DEFAULT_DAYS_BACK_TO_HEAL = 7

log = get_logger("update_bybit_prices")


def update_bybit_prices(
    instrument_list=None,
    force_full_refresh: bool = False,
    dry_run: bool = False,
    days_back_to_heal: int = DEFAULT_DAYS_BACK_TO_HEAL,
):
    """Fetch fresh ByBit data for the given instruments and upsert into MongoDB.

    :param instrument_list: list of instrument codes; defaults to all ByBit
        instruments from the configuration.
    :param force_full_refresh: if True refetch the complete history from the
        API instead of just the tail after the last date in Mongo.
    :param dry_run: if True fetch + report but write nothing.
    :param days_back_to_heal: when doing an incremental update re-fetch at least
        this many days before the last Mongo date to heal any small gaps.
    :return: None
    """
    if instrument_list is None:
        instrument_list = get_list_of_bybit_instruments()
    instrument_list = list(instrument_list)

    api = bybitAPI(log=log)
    ohlcv_store = mongoBybitOHLCVData()
    funding_store = mongoBybitFundingData()

    log.info(
        "Updating %d ByBit instruments into MongoDB (force_full_refresh=%s, dry_run=%s)"
        % (len(instrument_list), force_full_refresh, dry_run)
    )

    for instrument_code in instrument_list:
        try:
            _update_instrument(
                instrument_code,
                api=api,
                ohlcv_store=ohlcv_store,
                funding_store=funding_store,
                force_full_refresh=force_full_refresh,
                dry_run=dry_run,
                days_back_to_heal=days_back_to_heal,
            )
        except Exception as exception:
            log.critical(
                "Error updating %s: %s" % (instrument_code, str(exception)),
                instrument_code=instrument_code,
            )

    log.info("ByBit data update finished")


def _update_instrument(
    instrument_code: str,
    api: bybitAPI,
    ohlcv_store: mongoBybitOHLCVData,
    funding_store: mongoBybitFundingData,
    force_full_refresh: bool,
    dry_run: bool,
    days_back_to_heal: int,
):
    symbol = api.instrument_code_to_bybit_symbol(instrument_code)

    ohlcv_fresh = _fetch_fresh_ohlcv(
        instrument_code, symbol, api, ohlcv_store, force_full_refresh, days_back_to_heal
    )

    existing_ohlcv = ohlcv_store.get_ohlcv(instrument_code)
    merged_ohlcv = _merge_and_dedupe(existing_ohlcv, ohlcv_fresh)

    funding_fresh = api.fetch_funding_rate_history_all(symbol, use_cache=False)
    existing_funding = funding_store.get_funding(instrument_code)
    merged_funding = _merge_and_dedupe(existing_funding, funding_fresh)

    n_ohlcv_new = _number_of_rows_new(existing_ohlcv, merged_ohlcv)
    n_funding_new = _number_of_rows_new(existing_funding, merged_funding)

    log.info(
        "%s: ohlcv %d rows (new %d), funding %d rows (new %d)"
        % (
            instrument_code,
            len(merged_ohlcv),
            n_ohlcv_new,
            len(merged_funding),
            n_funding_new,
        ),
        instrument_code=instrument_code,
    )

    if dry_run:
        log.info(
            "Dry run - not writing %s to MongoDB or cache" % instrument_code,
            instrument_code=instrument_code,
        )
        return

    _write_ohlcv(ohlcv_store, api, symbol, instrument_code, merged_ohlcv)
    _write_funding(funding_store, api, symbol, instrument_code, merged_funding)


def _fetch_fresh_ohlcv(
    instrument_code: str,
    symbol: str,
    api: bybitAPI,
    ohlcv_store: mongoBybitOHLCVData,
    force_full_refresh: bool,
    days_back_to_heal: int,
) -> pd.DataFrame:
    if force_full_refresh:
        log.info(
            "%s: full history refresh from API" % instrument_code,
            instrument_code=instrument_code,
        )
        return api.fetch_ohlcv_all(symbol, timeframe="1d", use_cache=False)

    last_datetime = ohlcv_store.get_last_datetime(instrument_code)
    if last_datetime is None:
        log.info(
            "%s: no data in Mongo, seeding full history from API" % instrument_code,
            instrument_code=instrument_code,
        )
        return api.fetch_ohlcv_all(symbol, timeframe="1d", use_cache=False)

    since_ms = _since_ms_to_re_fetch(last_datetime, days_back_to_heal)
    log.debug(
        "%s: incremental fetch since %s"
        % (
            instrument_code,
            datetime.datetime.fromtimestamp(since_ms / 1000.0).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        ),
        instrument_code=instrument_code,
    )
    return api.fetch_ohlcv_all(symbol, timeframe="1d", since=since_ms, use_cache=False)


def _since_ms_to_re_fetch(last_datetime, days_back_to_heal: int) -> int:
    re_fetch_from = last_datetime - datetime.timedelta(days=days_back_to_heal)
    return int(re_fetch_from.timestamp() * 1000)


def _merge_and_dedupe(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if len(existing) == 0:
        return fresh
    if len(fresh) == 0:
        return existing
    merged = pd.concat([existing, fresh])
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged.sort_index()


def _number_of_rows_new(existing: pd.DataFrame, merged: pd.DataFrame) -> int:
    if len(existing) == 0:
        return len(merged)
    n_brand_new = len(merged.index.difference(existing.index))
    common = merged.index.intersection(existing.index)
    n_changed = int((merged.loc[common] != existing.loc[common]).any(axis=1).sum())
    return n_brand_new + n_changed


def _write_ohlcv(
    ohlcv_store: mongoBybitOHLCVData,
    api: bybitAPI,
    symbol: str,
    instrument_code: str,
    merged_ohlcv: pd.DataFrame,
):
    ohlcv_store.write_ohlcv(instrument_code, merged_ohlcv)
    # keep the local backtest CSV cache in sync too
    api.refresh_cached_ohlcv(symbol, merged_ohlcv)
    log.info(
        "Wrote %d OHLCV rows for %s to MongoDB and cache"
        % (len(merged_ohlcv), instrument_code),
        instrument_code=instrument_code,
    )


def _write_funding(
    funding_store: mongoBybitFundingData,
    api: bybitAPI,
    symbol: str,
    instrument_code: str,
    merged_funding: pd.DataFrame,
):
    funding_store.write_funding(instrument_code, merged_funding)
    api.refresh_cached_funding(symbol, merged_funding)
    log.info(
        "Wrote %d funding rows for %s to MongoDB and cache"
        % (len(merged_funding), instrument_code),
        instrument_code=instrument_code,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Update ByBit prices into MongoDB for production"
    )
    parser.add_argument(
        "--instruments",
        nargs="*",
        default=None,
        help="Instrument codes to update (default: all ByBit instruments from config)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force a full history refetch from the API, ignoring the last Mongo date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report row counts without writing anything",
    )
    args = parser.parse_args()

    update_bybit_prices(
        instrument_list=args.instruments,
        force_full_refresh=args.full,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
