import datetime

import pytest

from syscore.exceptions import missingData, existingData

from sysobjects.production.bybit_open_orders import (
    bybitOpenOrder,
    listOfBybitOpenOrders,
    STATUS_OPEN,
    STATUS_FILLED,
)
from sysdata.production.bybit_open_orders import bybitOpenOrderData


def _make_order(order_id="ORDER_1", instrument_code="LINK_BYBIT", **kwargs):
    default_kwargs = dict(
        symbol="LINK/USDT:USDT",
        side="buy",
        qty_blocks=3,
        qty_coin=0.3,
        limit_price=11.5,
        placed_datetime=datetime.datetime(2026, 1, 1, 9, 0, 0),
        attempts=0,
        status=STATUS_OPEN,
    )
    default_kwargs.update(kwargs)
    return bybitOpenOrder(
        order_id=order_id, instrument_code=instrument_code, **default_kwargs
    )


def test_bybit_open_order_dict_round_trip():
    order = _make_order()
    order_from_dict = bybitOpenOrder.from_dict(order.as_dict())

    assert order_from_dict == order
    assert order_from_dict.placed_datetime == datetime.datetime(2026, 1, 1, 9, 0, 0)
    assert order_from_dict.attempts == 0
    assert order_from_dict.status == STATUS_OPEN


def test_bybit_open_order_from_dict_with_missing_optional_fields():
    order = _make_order()
    attr_dict = order.as_dict()
    attr_dict.pop("status")
    attr_dict.pop("attempts")

    order_from_dict = bybitOpenOrder.from_dict(attr_dict)
    assert order_from_dict.status == STATUS_OPEN
    assert order_from_dict.attempts == 0


def test_bybit_open_order_signed_qty_blocks():
    assert _make_order(side="buy", qty_blocks=3).signed_qty_blocks == 3
    assert _make_order(side="sell", qty_blocks=5).signed_qty_blocks == -5


def test_list_of_bybit_open_orders_helpers():
    order_a = _make_order(order_id="A", instrument_code="LINK_BYBIT")
    order_b = _make_order(order_id="B", instrument_code="LINK_BYBIT")
    order_c = _make_order(order_id="C", instrument_code="BTC_BYBIT")

    orders = listOfBybitOpenOrders([order_a, order_b, order_c])

    assert orders.order_for_instrument("LINK_BYBIT").order_id == "A"
    assert orders.order_for_instrument("DOES_NOT_EXIST") is None
    assert set(orders.get_list_of_instrument_codes()) == {"LINK_BYBIT", "BTC_BYBIT"}
    assert len(orders.for_instrument("LINK_BYBIT")) == 2


class StubBybitOpenOrderData(bybitOpenOrderData):
    def __init__(self):
        super().__init__()
        self._stored = {}

    def _get_open_order_as_dict_or_missing_data(self, order_id):
        if order_id not in self._stored:
            raise missingData("no order %s" % order_id)
        return dict(self._stored[order_id])

    def _add_open_order_as_dict(self, open_order_dict):
        order_id = open_order_dict["order_id"]
        if order_id in self._stored:
            raise existingData("order %s already stored" % order_id)
        self._stored[order_id] = dict(open_order_dict)

    def _update_open_order_as_dict(self, open_order_dict):
        self._stored[open_order_dict["order_id"]] = dict(open_order_dict)

    def _delete_open_order(self, order_id):
        if order_id not in self._stored:
            raise missingData("no order %s" % order_id)
        del self._stored[order_id]

    def _get_all_open_orders(self):
        return [dict(stored) for stored in self._stored.values()]


@pytest.fixture
def stub_data_layer():
    return StubBybitOpenOrderData()


def test_add_and_get_open_orders(stub_data_layer):
    order = _make_order()
    stub_data_layer.add_open_order(order)
    assert stub_data_layer.get_open_order_for_order_id("ORDER_1") == order
    assert stub_data_layer.get_open_order_for_instrument("LINK_BYBIT") == order
    assert stub_data_layer.have_open_order_for_instrument("LINK_BYBIT")
    assert stub_data_layer.get_list_of_instrument_codes_with_open_orders() == [
        "LINK_BYBIT"
    ]


def test_get_open_order_missing(stub_data_layer):
    assert stub_data_layer.get_open_order_for_order_id("NOPE") is None
    assert stub_data_layer.get_open_order_for_instrument("LINK_BYBIT") is None
    assert not stub_data_layer.have_open_order_for_instrument("LINK_BYBIT")
    stub_data_layer.delete_open_order_if_present("NOPE")


def test_update_and_delete_open_orders(stub_data_layer):
    order = _make_order()
    stub_data_layer.add_open_order(order)

    order.attempts = 2
    order.status = STATUS_FILLED
    stub_data_layer.update_open_order(order)
    updated = stub_data_layer.get_open_order_for_order_id("ORDER_1")
    assert updated.attempts == 2
    assert updated.status == STATUS_FILLED

    stub_data_layer.delete_open_order("ORDER_1")
    assert stub_data_layer.get_open_order_for_order_id("ORDER_1") is None


def test_add_duplicate_order_is_rejected(stub_data_layer):
    order = _make_order()
    stub_data_layer.add_open_order(order)
    with pytest.raises(Exception):
        stub_data_layer.add_open_order(_make_order(order_id="ORDER_1"))
