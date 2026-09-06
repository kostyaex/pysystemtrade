import pandas as pd

from sysdata.futures.multiple_prices import futuresMultiplePricesData
from sysobjects.multiple_prices import futuresMultiplePrices
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from syscore.constants import arg_not_supplied
from syslogging.logger import *

PERPETUAL_CONTRACT_DATE = "20991200"


class bybitFuturesMultiplePricesData(futuresMultiplePricesData):
    """
    Read and write multiple prices for ByBit perpetual contracts.

    For perpetuals:
    - PRICE = perpetual close price
    - CARRY = price * (1 + funding_rate_daily) - funding-weighted carry
    - FORWARD = price (forward ~= spot for perpetual)
    - All *_CONTRACT = '20991200' (synthetic perpetual contract date)

    Funding rate is fetched from ByBit API and aggregated to daily frequency.
    """

    def __init__(
        self,
        bybit_api: bybitAPI = arg_not_supplied,
        log=get_logger("bybitFuturesMultiplePrices"),
    ):
        super().__init__(log=log)
        if bybit_api is arg_not_supplied:
            bybit_api = bybitAPI(log=log)
        self._bybit_api = bybit_api

    def __repr__(self):
        return "bybitFuturesMultiplePricesData using ByBit API"

    @property
    def bybit_api(self) -> bybitAPI:
        return self._bybit_api

    def get_list_of_instruments(self) -> list:
        return get_list_of_bybit_instruments()

    def _get_multiple_prices_without_checking(
        self, instrument_code: str
    ) -> futuresMultiplePrices:
        symbol = self.bybit_api.instrument_code_to_bybit_symbol(instrument_code)

        self.log.info(
            "Fetching multiple prices for %s (ByBit symbol: %s)"
            % (instrument_code, symbol),
            instrument_code=instrument_code,
        )

        ohlcv = self.bybit_api.fetch_ohlcv_all(symbol, timeframe="1d")
        if len(ohlcv) == 0:
            self.log.warning(
                "No OHLCV data returned for %s" % instrument_code,
                instrument_code=instrument_code,
            )
            return futuresMultiplePrices.create_empty()

        funding = self.bybit_api.fetch_funding_rate_history_all(symbol)
        daily_funding = self._aggregate_funding_to_daily(funding, ohlcv.index)

        price = ohlcv["FINAL"]
        carry = price * (1 + daily_funding.reindex(price.index).fillna(0))
        forward = price

        contract = pd.Series(PERPETUAL_CONTRACT_DATE, index=price.index)

        multiple_prices = pd.DataFrame(
            {
                "CARRY": carry,
                "CARRY_CONTRACT": contract,
                "PRICE": price,
                "PRICE_CONTRACT": contract,
                "FORWARD": forward,
                "FORWARD_CONTRACT": contract,
            }
        )

        return futuresMultiplePrices(multiple_prices)

    def _aggregate_funding_to_daily(
        self, funding: pd.DataFrame, daily_index: pd.DatetimeIndex
    ) -> pd.Series:
        """
        Aggregate 8-hour funding rates to daily frequency.

        Takes the mean of all funding rates within each day.
        """
        if len(funding) == 0:
            return pd.Series(0.0, index=daily_index)

        daily_funding = funding["fundingRate"].resample("D").mean()
        daily_funding = daily_funding.reindex(daily_index, method="ffill")
        daily_funding = daily_funding.fillna(0)

        return daily_funding

    def _add_multiple_prices_without_checking_for_existing_entry(
        self, instrument_code: str, multiple_price_data: futuresMultiplePrices
    ):
        self.log.info(
            "ByBit multiple prices are generated from API - nothing to write locally",
            instrument_code=instrument_code,
        )

    def _delete_multiple_prices_without_any_warning_be_careful(
        self, instrument_code: str
    ):
        self.log.info(
            "ByBit multiple prices are generated from API - nothing to delete locally",
            instrument_code=instrument_code,
        )
