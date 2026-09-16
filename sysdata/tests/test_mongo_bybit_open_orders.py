import datetime

import pytest

from sysdata.mongodb.mongo_bybit_open_orders import mongoBybitOpenOrderData
from sysdata.mongodb.mongo_connection import mongoDb
from sysobjects.production.bybit_open_orders import bybitOpenOrder, STATUS_OPEN

TEST_DATABASE_NAME = "test_bybit_open_orders"


def _mongo_available() -> bool:
    try:
        db = mongoDb(mongo_db=TEST_DATABASE_NAME)
        db.client.admin.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture
def mongo_layer():
    if not _mongo_available():
        pytest.skip("Mongo not available, cannot test mongoBybitOpenOrderData")
    db = mongoDb(mongo_db=TEST_DATABASE_NAME)
    db.client.drop_database(TEST_DATABASE_NAME)
    data = mongoBybitOpenOrderData(mongo_db=db)
    yield data
    db.client.drop_database(TEST_DATABASE_NAME)


def _make_order(order_id="ORDER_1", **kwargs):
    defaults = dict(
        instrument_code="LINK_BYBIT",
        symbol="LINK/USDT:USDT",
        side="buy",
        qty_blocks=3,
        qty_coin=0.3,
        limit_price=11.5,
        placed_datetime=datetime.datetime(2026, 1, 1, 9, 0, 0),
        attempts=0,
        status=STATUS_OPEN,
    )
    defaults.update(kwargs)
    return bybitOpenOrder(order_id=order_id, **defaults)


def test_add_get_update_delete_round_trip(mongo_layer):
    order = _make_order()
    mongo_layer.add_open_order(order)
    assert mongo_layer.get_open_order_for_order_id("ORDER_1") == order

    order.attempts = 2
    order.status = "FILLED"
    mongo_layer.update_open_order(order)
    updated = mongo_layer.get_open_order_for_order_id("ORDER_1")
    assert updated.attempts == 2
    assert updated.status == "FILLED"

    mongo_layer.delete_open_order("ORDER_1")
    assert mongo_layer.get_open_order_for_order_id("ORDER_1") is None


def test_get_open_order_missing(mongo_layer):
    assert mongo_layer.get_open_order_for_order_id("NOPE") is None
    mongo_layer.delete_open_order_if_present("NOPE")


def test_duplicate_order_is_rejected(mongo_layer):
    mongo_layer.add_open_order(_make_order())
    with pytest.raises(Exception):
        mongo_layer.add_open_order(_make_order())


def test_get_all_open_orders_and_instrument_helpers(mongo_layer):
    mongo_layer.add_open_order(_make_order(order_id="A", instrument_code="LINK_BYBIT"))
    mongo_layer.add_open_order(_make_order(order_id="B", instrument_code="LINK_BYBIT"))
    mongo_layer.add_open_order(
        _make_order(order_id="C", instrument_code="BTC_BYBIT", symbol="BTC/USDT:USDT")
    )

    orders = mongo_layer.get_all_open_orders()
    assert set(orders.get_list_of_instrument_codes()) == {"LINK_BYBIT", "BTC_BYBIT"}
    assert len(orders.for_instrument("LINK_BYBIT")) == 2
    assert mongo_layer.have_open_order_for_instrument("LINK_BYBIT")
    assert mongo_layer.get_open_order_for_instrument("LINK_BYBIT").order_id in {
        "A",
        "B",
    }
    assert mongo_layer.get_open_order_for_instrument("BTC_BYBIT").order_id == "C"
    assert sorted(mongo_layer.get_list_of_instrument_codes_with_open_orders()) == [
        "BTC_BYBIT",
        "LINK_BYBIT",
    ]
