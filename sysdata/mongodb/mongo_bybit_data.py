"""
MongoDB storage for raw ByBit data (daily OHLCV candles and funding rates).

Used by the production data pipeline: a scheduled process (see
`sysproduction/update_bybit_prices.py`) writes fresh data from the ByBit API
into MongoDB, and the read-only ByBit data source (see
`sysdata/bybit/bybit_mongo_api.py`) serves it back to the system.

Data is stored in the 'bybit' database by default (a dedicated database, kept
separate from the pysystemtrade 'production' database). Pass an explicit
`mongo_db` argument to override.

Collections:
- bybit_ohlcv   : one document per instrument per daily candle
- bybit_funding : one document per instrument per funding period
"""

import pandas as pd
from pymongo import ASCENDING, UpdateOne

from syscore.constants import arg_not_supplied
from sysdata.mongodb.mongo_connection import mongoConnection, mongoDb
from syslogging.logger import *

OHLCV_COLLECTION = "bybit_ohlcv"
FUNDING_COLLECTION = "bybit_funding"

BYBIT_DATABASE_NAME = "bybit"

OHLCV_COLUMNS = ["OPEN", "HIGH", "LOW", "FINAL", "VOLUME"]

INSTRUMENT_KEY = "instrument_code"
DATETIME_KEY = "datetime"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_mongo_db_for_bybit(mongo_db=arg_not_supplied) -> mongoDb:
    if mongo_db is arg_not_supplied:
        mongo_db = mongoDb(mongo_db=BYBIT_DATABASE_NAME)
    return mongo_db


def _datetime_to_str(dt) -> str:
    return pd.Timestamp(dt).strftime(DATETIME_FORMAT)


def _str_to_datetime(dt_str) -> pd.Timestamp:
    return pd.Timestamp(dt_str)


class _mongoBybitTimeSeriesData(object):
    """
    Generic upsert/read of per-instrument per-timestamp time series in Mongo.
    """

    def __init__(self, collection_name: str, mongo_db=arg_not_supplied):
        self._mongo = mongoConnection(
            collection_name, mongo_db=get_mongo_db_for_bybit(mongo_db)
        )
        self._ensure_index()

    def _ensure_index(self):
        self._mongo.create_compound_index(
            {
                "keys": {
                    INSTRUMENT_KEY: ASCENDING,
                    DATETIME_KEY: ASCENDING,
                },
                "unique": True,
            }
        )

    def __repr__(self):
        return str(self._mongo)

    @property
    def collection(self):
        return self._mongo.collection

    def get_list_of_instruments(self) -> list:
        return self.collection.distinct(INSTRUMENT_KEY)

    def get_last_datetime(self, instrument_code: str):
        doc = self.collection.find_one(
            {INSTRUMENT_KEY: instrument_code}, sort=[(DATETIME_KEY, -1)]
        )
        if doc is None:
            return None
        return _str_to_datetime(doc[DATETIME_KEY])

    def get_all_data_dict_list(self, instrument_code: str) -> list:
        cursor = self.collection.find({INSTRUMENT_KEY: instrument_code}).sort(
            DATETIME_KEY, 1
        )
        return [doc for doc in cursor]

    def write_data_from_df(self, instrument_code: str, data_df: pd.DataFrame):
        if len(data_df) == 0:
            return
        operations = [
            UpdateOne(
                {
                    INSTRUMENT_KEY: instrument_code,
                    DATETIME_KEY: _datetime_to_str(datetime_index),
                },
                {
                    "$set": self._record_for_datetime(
                        instrument_code, datetime_index, row
                    )
                },
                upsert=True,
            )
            for datetime_index, row in data_df.iterrows()
        ]
        self.collection.bulk_write(operations, ordered=False)

    def _record_for_datetime(self, instrument_code: str, datetime_index, row) -> dict:
        raise NotImplementedError

    def delete_data_for_instrument(self, instrument_code: str):
        self.collection.delete_many({INSTRUMENT_KEY: instrument_code})


class mongoBybitOHLCVData(_mongoBybitTimeSeriesData):
    def __init__(self, mongo_db=arg_not_supplied):
        super().__init__(OHLCV_COLLECTION, mongo_db=mongo_db)

    def __repr__(self):
        return "MongoDB ByBit OHLCV store: %s" % str(self._mongo)

    def _record_for_datetime(self, instrument_code, datetime_index, row) -> dict:
        return {
            INSTRUMENT_KEY: instrument_code,
            DATETIME_KEY: _datetime_to_str(datetime_index),
            "open": float(row["OPEN"]),
            "high": float(row["HIGH"]),
            "low": float(row["LOW"]),
            "final": float(row["FINAL"]),
            "volume": float(row["VOLUME"]),
        }

    def get_ohlcv(self, instrument_code: str) -> pd.DataFrame:
        dict_list = self.get_all_data_dict_list(instrument_code)
        if len(dict_list) == 0:
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index(
                pd.DatetimeIndex([], name="DATETIME")
            )

        df = pd.DataFrame(
            [
                {
                    "OPEN": record["open"],
                    "HIGH": record["high"],
                    "LOW": record["low"],
                    "FINAL": record["final"],
                    "VOLUME": record["volume"],
                    "DATETIME": _str_to_datetime(record[DATETIME_KEY]),
                }
                for record in dict_list
            ]
        )
        df.set_index("DATETIME", inplace=True)
        return df[OHLCV_COLUMNS].sort_index()

    def write_ohlcv(self, instrument_code: str, ohlcv_df: pd.DataFrame):
        self.write_data_from_df(instrument_code, ohlcv_df)

    def get_list_of_instruments(self) -> list:
        return super().get_list_of_instruments()

    def get_last_datetime(self, instrument_code: str):
        return super().get_last_datetime(instrument_code)

    def delete_ohlcv(self, instrument_code: str):
        self.delete_data_for_instrument(instrument_code)


class mongoBybitFundingData(_mongoBybitTimeSeriesData):
    def __init__(self, mongo_db=arg_not_supplied):
        super().__init__(FUNDING_COLLECTION, mongo_db=mongo_db)

    def __repr__(self):
        return "MongoDB ByBit funding store: %s" % str(self._mongo)

    def _record_for_datetime(self, instrument_code, datetime_index, row) -> dict:
        return {
            INSTRUMENT_KEY: instrument_code,
            DATETIME_KEY: _datetime_to_str(datetime_index),
            "funding_rate": float(row["fundingRate"]),
        }

    def get_funding(self, instrument_code: str) -> pd.DataFrame:
        dict_list = self.get_all_data_dict_list(instrument_code)
        if len(dict_list) == 0:
            return pd.DataFrame(columns=["fundingRate"]).set_index(
                pd.DatetimeIndex([], name="DATETIME")
            )

        df = pd.DataFrame(
            [
                {
                    "fundingRate": record["funding_rate"],
                    "DATETIME": _str_to_datetime(record[DATETIME_KEY]),
                }
                for record in dict_list
            ]
        )
        df.set_index("DATETIME", inplace=True)
        return df[["fundingRate"]].sort_index()

    def write_funding(self, instrument_code: str, funding_df: pd.DataFrame):
        self.write_data_from_df(instrument_code, funding_df)

    def get_list_of_instruments(self) -> list:
        return super().get_list_of_instruments()

    def get_last_datetime(self, instrument_code: str):
        return super().get_last_datetime(instrument_code)

    def delete_funding(self, instrument_code: str):
        self.delete_data_for_instrument(instrument_code)


if __name__ == "__main__":
    import doctest

    doctest.testmod()
