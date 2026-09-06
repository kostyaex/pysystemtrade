import os
import time

import pandas as pd
from syscore.constants import arg_not_supplied
from syslogging.logger import *

DEFAULT_BYBIT_SYMBOL_SUFFIX = ":USDT"
BYBIT_HISTORY_START_MS = 1546300800000  # 2019-01-01

_BYBIT_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
BYBIT_DATA_FOLDER = os.path.join(_BYBIT_MODULE_DIR, "..", "..", "data", "futures", "bybit")
OHLCV_CACHE_FOLDER = os.path.join(BYBIT_DATA_FOLDER, "ohlcv")
FUNDING_CACHE_FOLDER = os.path.join(BYBIT_DATA_FOLDER, "funding")

NUM_FETCH_RETRIES = 4
RETRY_BACKOFF_SECONDS = 5


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

    def _fetch_with_retries(self, fetch_call, *args, **kwargs):
        last_exception = None
        for _ in range(NUM_FETCH_RETRIES):
            try:
                return fetch_call(*args, **kwargs)
            except Exception as exception:
                last_exception = exception
                self.log.debug(
                    "Fetch failed (%s), backing off %.0fs and retrying"
                    % (exception, RETRY_BACKOFF_SECONDS)
                )
                time.sleep(RETRY_BACKOFF_SECONDS)
        raise last_exception

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
        raw_data = self._fetch_with_retries(
            self.exchange.fetch_ohlcv, symbol, timeframe, since, limit
        )

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
        Fetch all OHLCV data with pagination, cached locally on disk.

        Full-history (1d from 2019-01-01) data is cached in
        data/futures/bybit/ohlcv so that backtests don't hit the ByBit API
        repeatedly. Delete that folder to force a refresh.

        :param symbol: trading pair, e.g. 'BTC/USDT:USDT'
        :param timeframe: candle timeframe
        :param since: timestamp in ms to start from. Defaults to 2019-01-01.
        :return: DataFrame with all OHLCV data
        """
        if since is None:
            since = BYBIT_HISTORY_START_MS

        use_cache = timeframe == "1d" and since == BYBIT_HISTORY_START_MS

        if use_cache:
            cached = self._load_cached_ohlcv(symbol)
            if cached is not None:
                return cached

        result = self._fetch_ohlcv_all_from_api(symbol, timeframe, since)

        if use_cache:
            self._save_cached_ohlcv(symbol, result)

        return result

    def _fetch_ohlcv_all_from_api(
        self,
        symbol: str,
        timeframe: str,
        since: int,
    ) -> pd.DataFrame:
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

    def _load_cached_ohlcv(self, symbol: str):
        return self._load_cache_folder_file(OHLCV_CACHE_FOLDER, symbol)

    def _save_cached_ohlcv(self, symbol: str, data: pd.DataFrame):
        self._save_cache_folder_file(OHLCV_CACHE_FOLDER, symbol, data)

    def _load_cached_funding(self, symbol: str):
        return self._load_cache_folder_file(FUNDING_CACHE_FOLDER, symbol)

    def _save_cached_funding(self, symbol: str, data: pd.DataFrame):
        self._save_cache_folder_file(FUNDING_CACHE_FOLDER, symbol, data)

    def _load_cache_folder_file(self, folder: str, symbol: str):
        path = self._cache_file_path(folder, symbol)
        if not os.path.isfile(path):
            return None
        return pd.read_csv(path, index_col=0, parse_dates=True)

    def _save_cache_folder_file(
        self, folder: str, symbol: str, data: pd.DataFrame
    ):
        if len(data) == 0:
            return
        path = self._cache_file_path(folder, symbol)
        os.makedirs(folder, exist_ok=True)
        data.to_csv(path)

    @staticmethod
    def _cache_file_path(folder: str, symbol: str) -> str:
        base = symbol.split("/")[0].lower()
        return os.path.join(folder, base + ".csv")

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
        raw_data = self._fetch_with_retries(
            self.exchange.fetch_funding_rate_history, symbol, since, limit
        )

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

        Data is cached in data/futures/bybit/funding. Delete that folder to
        force a refresh.

        :param symbol: trading pair
        :param since: if provided, only records at/after this timestamp are kept
        :return: DataFrame with all available funding rate history
        """
        cached = self._load_cached_funding(symbol)
        if cached is not None:
            result = cached
        else:
            result = self._fetch_funding_rate_history_all_from_api(symbol)
            self._save_cached_funding(symbol, result)

        if since is not None:
            result = result[result.index >= pd.Timestamp(since, unit="ms")]

        return result

    def _fetch_funding_rate_history_all_from_api(self, symbol: str) -> pd.DataFrame:
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
