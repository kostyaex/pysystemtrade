"""
Read-only ByBit data source backed by MongoDB.

Implements the same interface the bybit* price data classes expect
(`fetch_ohlcv_all`, `fetch_funding_rate_history_all`, symbol conversions) but
reads from the MongoDB 'bybit' database instead of the live ByBit API.

Usage (production): the scheduled updater
(`sysproduction/update_bybit_prices.py`) writes fresh data in MongoDB; the
backtest / system then builds `bybitFuturesSimData(data_source="mongo")` which
serves that data back.
"""

import pandas as pd

from syscore.constants import arg_not_supplied
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.mongodb.mongo_bybit_data import (
    mongoBybitOHLCVData,
    mongoBybitFundingData,
)
from syslogging.logger import *


class bybitMongoAPI(bybitAPI):
    """
    ByBit API-compatible facade that reads cached-by-MongoDB data.

    No network calls are made; data must already be present in MongoDB,
    populated by `sysproduction/update_bybit_prices.py`.
    """

    def __init__(self, mongo_db=arg_not_supplied, log=get_logger("bybitMongoAPI")):
        super().__init__(log=log)
        self._ohlcv_data = mongoBybitOHLCVData(mongo_db=mongo_db)
        self._funding_data = mongoBybitFundingData(mongo_db=mongo_db)

    def __repr__(self):
        return "bybitMongoAPI reading from %s" % str(self._ohlcv_data)

    @property
    def ohlcv_data(self) -> mongoBybitOHLCVData:
        return self._ohlcv_data

    @property
    def funding_data(self) -> mongoBybitFundingData:
        return self._funding_data

    def fetch_ohlcv_all(
        self,
        symbol: str,
        timeframe: str = "1d",
        since=None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        instrument_code = self.bybit_symbol_to_instrument_code(symbol)
        ohlcv = self.ohlcv_data.get_ohlcv(instrument_code)
        if since is not None:
            ohlcv = ohlcv[ohlcv.index >= pd.Timestamp(since, unit="ms")]

        return ohlcv

    def fetch_funding_rate_history_all(
        self,
        symbol: str,
        since=None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        instrument_code = self.bybit_symbol_to_instrument_code(symbol)
        funding = self.funding_data.get_funding(instrument_code)
        if since is not None:
            funding = funding[funding.index >= pd.Timestamp(since, unit="ms")]

        return funding

    def get_list_of_instruments_with_data(self) -> list:
        return self.ohlcv_data.get_list_of_instruments()


if __name__ == "__main__":
    import doctest

    doctest.testmod()
