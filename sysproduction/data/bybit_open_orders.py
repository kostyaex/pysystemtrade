from sysdata.data_blob import dataBlob
from sysdata.mongodb.mongo_bybit_open_orders import mongoBybitOpenOrderData
from sysdata.production.bybit_open_orders import bybitOpenOrderData
from sysproduction.data.generic_production_data import productionDataLayerGeneric
from sysobjects.production.bybit_open_orders import (
    bybitOpenOrder,
    listOfBybitOpenOrders,
)


class dataBybitOpenOrders(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data: dataBlob) -> dataBlob:
        data.add_class_object(mongoBybitOpenOrderData)

        return data

    @property
    def db_open_order_data(self) -> bybitOpenOrderData:
        return self.data.db_bybit_open_order

    def add_open_order(self, open_order: bybitOpenOrder):
        self.db_open_order_data.add_open_order(open_order)

    def update_open_order(self, open_order: bybitOpenOrder):
        self.db_open_order_data.update_open_order(open_order)

    def delete_open_order(self, order_id: str):
        self.db_open_order_data.delete_open_order_if_present(order_id)

    def get_all_open_orders(self) -> listOfBybitOpenOrders:
        return self.db_open_order_data.get_all_open_orders()

    def get_open_order_for_order_id(self, order_id: str):
        return self.db_open_order_data.get_open_order_for_order_id(order_id)

    def get_open_order_for_instrument(self, instrument_code: str):
        return self.db_open_order_data.get_open_order_for_instrument(instrument_code)

    def have_open_order_for_instrument(self, instrument_code: str) -> bool:
        return self.db_open_order_data.have_open_order_for_instrument(instrument_code)

    def get_list_of_instrument_codes_with_open_orders(self) -> list:
        return self.db_open_order_data.get_list_of_instrument_codes_with_open_orders()
