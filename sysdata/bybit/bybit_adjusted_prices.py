import pandas as pd

from sysdata.futures.adjusted_prices import futuresAdjustedPricesData
from sysobjects.adjusted_prices import futuresAdjustedPrices
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from syscore.constants import arg_not_supplied
from syslogging.logger import *


class bybitFuturesAdjustedPricesData(futuresAdjustedPricesData):
    """
    Read and write adjusted prices for ByBit perpetual contracts.

    Uses ByBit API to fetch perpetual OHLCV data and stores as adjusted prices.
    """

    def __init__(
        self,
        bybit_api: bybitAPI = arg_not_supplied,
        log=get_logger("bybitFuturesAdjustedPrices"),
    ):
        super().__init__(log=log)
        if bybit_api is arg_not_supplied:
            bybit_api = bybitAPI(log=log)
        self._bybit_api = bybit_api

    def __repr__(self):
        return "bybitFuturesAdjustedPricesData using ByBit API"

    @property
    def bybit_api(self) -> bybitAPI:
        return self._bybit_api

    def get_list_of_instruments(self) -> list:
        """
        Return list of ByBit instruments for which we have config.
        """
        return get_list_of_bybit_instruments()

    def _get_adjusted_prices_without_checking(
        self, instrument_code: str
    ) -> futuresAdjustedPrices:
        symbol = self.bybit_api.instrument_code_to_bybit_symbol(instrument_code)
        self.log.info(
            "Fetching adjusted prices for %s (ByBit symbol: %s)"
            % (instrument_code, symbol),
            instrument_code=instrument_code,
        )

        ohlcv = self.bybit_api.fetch_ohlcv_all(symbol, timeframe="1d")

        if len(ohlcv) == 0:
            self.log.warning(
                "No OHLCV data returned for %s" % instrument_code,
                instrument_code=instrument_code,
            )
            return futuresAdjustedPrices.create_empty()

        adjusted_prices = futuresAdjustedPrices(ohlcv["FINAL"])

        return adjusted_prices

    def _add_adjusted_prices_without_checking_for_existing_entry(
        self, instrument_code: str, adjusted_price_data: futuresAdjustedPrices
    ):
        self.log.info(
            "Adjusted prices for %s fetched directly from ByBit API (no local storage needed)"
            % instrument_code,
            instrument_code=instrument_code,
        )

    def _delete_adjusted_prices_without_any_warning_be_careful(
        self, instrument_code: str
    ):
        self.log.info(
            "ByBit adjusted prices are fetched from API - nothing to delete locally",
            instrument_code=instrument_code,
        )
