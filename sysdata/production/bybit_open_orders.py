from syscore.exceptions import missingData
from sysdata.base_data import baseData
from syslogging.logger import *

from sysobjects.production.bybit_open_orders import (
    bybitOpenOrder,
    listOfBybitOpenOrders,
)


class bybitOpenOrderData(baseData):
    """
    Read and write open ByBit limit order records.

    One open record per instrument is expected (one open limit order per
    instrument); callers are responsible for checking whether an instrument
    already has an open order before adding a new one.
    """

    def __init__(self, log=get_logger("bybitOpenOrderData")):
        super().__init__(log=log)

    def add_open_order(self, open_order: bybitOpenOrder):
        self._add_open_order_as_dict(open_order.as_dict())

    def update_open_order(self, open_order: bybitOpenOrder):
        self._update_open_order_as_dict(open_order.as_dict())

    def delete_open_order(self, order_id: str):
        self._delete_open_order(order_id)

    def delete_open_order_if_present(self, order_id: str):
        try:
            self.delete_open_order(order_id)
        except missingData:
            pass

    def get_all_open_orders(self) -> listOfBybitOpenOrders:
        all_open_order_dicts = self._get_all_open_orders()
        list_of_open_orders = [
            bybitOpenOrder.from_dict(open_order_dict)
            for open_order_dict in all_open_order_dicts
        ]

        return listOfBybitOpenOrders(list_of_open_orders)

    def get_open_order_for_order_id(self, order_id: str):
        try:
            open_order_dict = self._get_open_order_as_dict_or_missing_data(order_id)
        except missingData:
            return None
        return bybitOpenOrder.from_dict(open_order_dict)

    def get_open_order_for_instrument(self, instrument_code: str):
        all_open_orders = self.get_all_open_orders()
        return all_open_orders.order_for_instrument(instrument_code)

    def have_open_order_for_instrument(self, instrument_code: str) -> bool:
        return self.get_open_order_for_instrument(instrument_code) is not None

    def get_list_of_instrument_codes_with_open_orders(self) -> list:
        open_orders = self.get_all_open_orders()
        return open_orders.get_list_of_instrument_codes()

    def _get_open_order_as_dict_or_missing_data(self, order_id: str) -> dict:
        raise NotImplementedError

    def _add_open_order_as_dict(self, open_order_dict: dict):
        raise NotImplementedError

    def _update_open_order_as_dict(self, open_order_dict: dict):
        raise NotImplementedError

    def _delete_open_order(self, order_id: str):
        raise NotImplementedError

    def _get_all_open_orders(self) -> list:
        raise NotImplementedError
