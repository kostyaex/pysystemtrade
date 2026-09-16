from syscore.constants import arg_not_supplied
from sysdata.mongodb.mongo_generic import mongoDataWithSingleKey
from sysdata.production.bybit_open_orders import bybitOpenOrderData
from sysobjects.production.bybit_open_orders import ORDER_ID_KEY
from syslogging.logger import *

BYBIT_OPEN_ORDERS_COLLECTION = "bybit_open_orders"


class mongoBybitOpenOrderData(bybitOpenOrderData):
    """
    Read and write open ByBit order records in MongoDB, keyed by exchange
    order id. Uses the default production database like the rest of the
    production order/trading records (a dedicated 'bybit' database only holds
    raw market time series such as candles and funding rates). Pass an explicit
    mongo_db to override.
    """

    def __init__(
        self,
        mongo_db=arg_not_supplied,
        log=get_logger("mongoBybitOpenOrderData"),
    ):
        super().__init__(log=log)
        self._mongo_data = mongoDataWithSingleKey(
            BYBIT_OPEN_ORDERS_COLLECTION, ORDER_ID_KEY, mongo_db=mongo_db
        )

    @property
    def mongo_data(self):
        return self._mongo_data

    def __repr__(self):
        return "Data connection for ByBit open orders, mongodb %s" % str(
            self.mongo_data
        )

    def _get_open_order_as_dict_or_missing_data(self, order_id: str) -> dict:
        return self.mongo_data.get_result_dict_for_key(order_id)

    def _add_open_order_as_dict(self, open_order_dict: dict):
        self.mongo_data.add_data(
            open_order_dict[ORDER_ID_KEY], open_order_dict, allow_overwrite=False
        )

    def _update_open_order_as_dict(self, open_order_dict: dict):
        self.mongo_data.add_data(
            open_order_dict[ORDER_ID_KEY], open_order_dict, allow_overwrite=True
        )

    def _delete_open_order(self, order_id: str):
        self.mongo_data.delete_data_without_any_warning(order_id)

    def _get_all_open_orders(self) -> list:
        all_open_order_dicts = self.mongo_data.get_list_of_result_dict_for_custom_dict(
            {ORDER_ID_KEY: {"$exists": True}}
        )

        return all_open_order_dicts
