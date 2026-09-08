import pandas as pd

from sysdata.fx.spotfx import fxPricesData
from sysobjects.spot_fx_prices import fxPrices
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from syscore.constants import arg_not_supplied
from syslogging.logger import *

DEFAULT_CURRENCY = "USD"


class bybitFxPricesData(fxPricesData):
    """
    Read and write FX prices for ByBit instruments.

    For ByBit perpetuals priced in USD, the FX rate is 1.0 for USDXXX pairs.
    For cross rates, we fetch from ByBit spot data if available.
    """

    def __init__(
        self,
        bybit_api: bybitAPI = arg_not_supplied,
        log=get_logger("bybitFxPricesData"),
    ):
        super().__init__(log=log)
        if bybit_api is arg_not_supplied:
            bybit_api = bybitAPI(log=log)
        self._bybit_api = bybit_api

    def __repr__(self):
        return "bybitFxPricesData using ByBit API"

    @property
    def bybit_api(self) -> bybitAPI:
        return self._bybit_api

    def get_list_of_fxcodes(self) -> list:
        return get_list_of_bybit_instruments()

    def _get_fx_prices_without_checking(self, code: str) -> fxPrices:
        currency1, currency2 = self._parse_fx_code(code)

        if currency1 == DEFAULT_CURRENCY and currency2 == DEFAULT_CURRENCY:
            return self._get_default_fx_prices()

        if currency2 == DEFAULT_CURRENCY:
            return self._get_usd_quote_fx_prices(currency1)

        if currency1 == DEFAULT_CURRENCY:
            return self._get_usd_base_fx_prices(currency2)

        return self._get_cross_rate(currency1, currency2)

    def _get_default_fx_prices(self) -> fxPrices:
        dates = pd.date_range(start="2019-01-01", end=pd.Timestamp.now(), freq="B")
        return fxPrices(pd.Series(1.0, index=dates))

    def _get_usd_quote_fx_prices(self, currency: str) -> fxPrices:
        symbol = "%s/USDT:USDT" % currency
        try:
            ohlcv = self.bybit_api.fetch_ohlcv_all(symbol, timeframe="1d")
        except Exception:
            self.log.warning(
                "Could not fetch %s from ByBit, returning default 1.0" % symbol
            )
            return self._get_default_fx_prices()

        if len(ohlcv) == 0:
            return self._get_default_fx_prices()

        return fxPrices(ohlcv["FINAL"])

    def _get_usd_base_fx_prices(self, currency: str) -> fxPrices:
        raw = self._get_usd_quote_fx_prices(currency)
        if len(raw) == 0:
            return fxPrices(pd.Series(dtype="float64"))
        return fxPrices(1.0 / raw)

    def _get_cross_rate(self, currency1: str, currency2: str) -> fxPrices:
        c1_vs_usd = self._get_usd_quote_fx_prices(currency1)
        c2_vs_usd = self._get_usd_quote_fx_prices(currency2)

        if len(c1_vs_usd) == 0 or len(c2_vs_usd) == 0:
            return fxPrices(pd.Series(dtype="float64"))

        aligned1, aligned2 = c1_vs_usd.align(c2_vs_usd, join="outer")
        cross = aligned1.ffill() / aligned2.ffill()

        return fxPrices(cross)

    def _add_fx_prices_without_checking_for_existing_entry(
        self, code: str, fx_price_data: fxPrices
    ):
        self.log.info("ByBit FX prices are fetched from API - nothing to write locally")

    def _delete_fx_prices_without_any_warning_be_careful(self, code: str):
        self.log.info(
            "ByBit FX prices are fetched from API - nothing to delete locally"
        )

    @staticmethod
    def _parse_fx_code(code: str) -> tuple:
        if len(code) == 6:
            return code[:3], code[3:]
        elif len(code) == 3:
            return code, DEFAULT_CURRENCY
        else:
            return code, DEFAULT_CURRENCY
