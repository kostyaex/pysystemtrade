import pandas as pd
from syscore.constants import arg_not_supplied
from syslogging.logger import *

DEFAULT_BYBIT_SYMBOL_SUFFIX = ":USDT"
BYBIT_HISTORY_START_MS = 1546300800000  # 2019-01-01


class bybitAPI:
    def __init__(
        self,
        exchange_id: str = "bybit",
        log=get_logger("bybitAPI"),
    ):
        self._exchange_id = exchange_id
        self._log = log
        self._exchange = None

    @property
    def log(self):
        return self._log

    @property
    def exchange(self):
        if self._exchange is None:
            self._exchange = self._create_exchange()
        return self._exchange

    def _create_exchange(self):
        try:
            import ccxt
        except ImportError:
            raise ImportError(
                "ccxt is required for ByBit data. Install with: pip install ccxt"
            )

        exchange_class = getattr(ccxt, self._exchange_id, None)
        if exchange_class is None:
            raise ValueError("Exchange %s not found in ccxt" % self._exchange_id)

        exchange = exchange_class(
            {"enableRateLimit": True, "timeout": 60000, "recurse": True}
        )
        return exchange

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        since=None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data from ByBit.

        :param symbol: trading pair, e.g. 'BTC/USDT:USDT'
        :param timeframe: candle timeframe, e.g. '1d', '1h', '8h'
        :param since: timestamp in ms to start from
        :param limit: max candles per request
        :return: DataFrame with columns OPEN, HIGH, LOW, FINAL, VOLUME and datetime index
        """
        raw_data = self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)

        if len(raw_data) == 0:
            return self._empty_ohlcv()

        df = pd.DataFrame(
            raw_data, columns=["timestamp", "OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]
        )
        df["DATETIME"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["DATETIME"] = df["DATETIME"].dt.tz_localize(None)
        df.set_index("DATETIME", inplace=True)
        df.drop("timestamp", axis=1, inplace=True)

        return df[["OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]]

    def fetch_ohlcv_all(
        self,
        symbol: str,
        timeframe: str = "1d",
        since=None,
    ) -> pd.DataFrame:
        """
        Fetch all OHLCV data with pagination.

        :param symbol: trading pair, e.g. 'BTC/USDT:USDT'
        :param timeframe: candle timeframe
        :param since: timestamp in ms to start from. Defaults to 2019-01-01.
        :return: DataFrame with all OHLCV data
        """
        if since is None:
            since = BYBIT_HISTORY_START_MS

        all_data = []
        current_since = since

        while True:
            batch = self.fetch_ohlcv(symbol, timeframe, current_since, limit=1000)
            if len(batch) == 0:
                break

            all_data.append(batch)
            last_timestamp = int(batch.index[-1].timestamp() * 1000)
            current_since = last_timestamp + 1

            if len(batch) < 1000:
                break

        if len(all_data) == 0:
            return self._empty_ohlcv()

        result = pd.concat(all_data)
        result = result[~result.index.duplicated(keep="last")]
        return result.sort_index()

    def fetch_funding_rate_history(
        self,
        symbol: str,
        since=None,
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Fetch funding rate history from ByBit.

        :param symbol: trading pair, e.g. 'BTC/USDT:USDT'
        :param since: timestamp in ms to start from
        :param limit: max results per request
        :return: DataFrame with columns fundingRate, DATETIME index
        """
        raw_data = self.exchange.fetch_funding_rate_history(symbol, since, limit)

        if len(raw_data) == 0:
            return pd.DataFrame(columns=["fundingRate"]).set_index(
                pd.DatetimeIndex([], name="DATETIME")
            )

        df = pd.DataFrame(raw_data)
        df["DATETIME"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["DATETIME"] = df["DATETIME"].dt.tz_localize(None)
        df.set_index("DATETIME", inplace=True)
        df = df[["fundingRate"]]

        return df

    def fetch_funding_rate_history_all(
        self,
        symbol: str,
        since=None,
    ) -> pd.DataFrame:
        """
        Fetch all available funding rate history from ByBit.

        ByBit's free public API only returns a limited recent window of funding
        history (~200 records at 8h intervals, about 66 days). It is not possible
        to page further back in time. So we fetch the single available batch.

        :param symbol: trading pair
        :param since: if provided, only records at/after this timestamp are kept
        :return: DataFrame with all available funding rate history
        """
        all_data = []

        batch = self.fetch_funding_rate_history(symbol, since=None, limit=200)
        if len(batch) > 0:
            all_data.append(batch)

        if len(all_data) == 0:
            return pd.DataFrame(columns=["fundingRate"]).set_index(
                pd.DatetimeIndex([], name="DATETIME")
            )

        result = pd.concat(all_data)
        result = result[~result.index.duplicated(keep="last")]
        result = result.sort_index()

        if since is not None:
            result = result[result.index >= pd.Timestamp(since, unit="ms")]

        return result

    def fetch_all_swap_symbols(self) -> list:
        """
        Fetch all available perpetual swap symbols.

        :return: list of symbol strings in ccxt format, e.g. ['BTC/USDT:USDT', ...]
        """
        self.exchange.load_markets()
        symbols = [
            symbol
            for symbol, market in self.exchange.markets.items()
            if market.get("swap") and market.get("active")
        ]
        return sorted(symbols)

    def instrument_code_to_bybit_symbol(self, instrument_code: str) -> str:
        """
        Convert pysystemtrade instrument code to ByBit ccxt symbol.

        E.g. 'BTC_BYBIT' -> 'BTC/USDT:USDT'
        """
        base = instrument_code.replace("_BYBIT", "")
        return base + "/USDT" + DEFAULT_BYBIT_SYMBOL_SUFFIX

    def bybit_symbol_to_instrument_code(self, symbol: str) -> str:
        """
        Convert ByBit ccxt symbol to pysystemtrade instrument code.

        E.g. 'BTC/USDT:USDT' -> 'BTC_BYBIT'
        """
        base = symbol.split("/")[0]
        return base + "_BYBIT"

    def _empty_ohlcv(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=["OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]
        ).set_index(pd.DatetimeIndex([], name="DATETIME"))
