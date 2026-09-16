import datetime

import pytest

from syscore.exceptions import missingData

import sysproduction.bybit_order_placement as placement_module
from sysproduction.bybit_order_placement import (
    bybitOrderPlacement,
    top_bid_from_order_book,
    top_ask_from_order_book,
    ACTION_PLACE,
    ACTION_SKIP_EXISTS,
    ACTION_SKIP_PRICE,
    ACTION_SKIP_BOOK,
)

from sysobjects.production.bybit_open_orders import (
    bybitOpenOrder,
    STATUS_OPEN,
)
from sysobjects.production.override import (
    DEFAULT_OVERRIDE,
    REDUCE_ONLY_OVERRIDE,
    NO_TRADE_OVERRIDE,
)

from sysdata.data_blob import dataBlob
from sysdata.production.bybit_open_orders import bybitOpenOrderData


def sample_trade(
    instrument_code="LINK_BYBIT",
    side="buy",
    qty_blocks=3,
    qty_coin=0.3,
    price=100.0,
    current_price=100.0,
    current_position=0,
    symbol="LINK/USDT:USDT",
):
    return {
        "instrument_code": instrument_code,
        "symbol": symbol,
        "side": side,
        "qty_blocks": qty_blocks,
        "qty_coin": qty_coin,
        "current_position_blocks": current_position,
        "current_price": current_price,
        "reference_price": price,
        "notional_usd": qty_coin * current_price,
        "order_type": "market",
        "limit_price": None,
    }


class StubBybitAPI:
    def __init__(self, min_amount=0.0, order_book=None):
        self.min_amount = min_amount
        self.order_book = order_book or {"bids": [[100.0, 5]], "asks": [[100.5, 5]]}
        self.created_limit_orders = []
        self.created_market_orders = []
        self.cancelled_orders = []
        self._fetch_order_result = {"status": "open", "filled": 0.0, "average": None}

    def fetch_order_book(self, symbol, limit=10):
        return self.order_book

    def get_min_order_amount(self, symbol):
        return self.min_amount

    def get_price_precision(self, symbol, price):
        return round(float(price), 4)

    def create_limit_order(self, symbol, side, amount, price):
        self.created_limit_orders.append((symbol, side, amount, price))
        return {
            "id": "LIMIT_%d" % len(self.created_limit_orders),
            "status": "open",
            "filled": 0.0,
        }

    def create_market_order(self, symbol, side, amount):
        order_id = "MKT_%d" % len(self.created_market_orders)
        self.created_market_orders.append((symbol, side, amount))
        return {
            "id": order_id,
            "status": "closed",
            "filled": amount,
            "average": 100.0,
        }

    def cancel_order(self, order_id, symbol):
        self.cancelled_orders.append((order_id, symbol))
        return {}

    def fetch_order(self, order_id, symbol):
        return dict(self._fetch_order_result)


class StubBybitOpenOrderData(bybitOpenOrderData):
    def __init__(self):
        super().__init__()
        self._stored = {}

    def _get_open_order_as_dict_or_missing_data(self, order_id):
        if order_id not in self._stored:
            raise missingData("no order %s" % order_id)
        return dict(self._stored[order_id])

    def _add_open_order_as_dict(self, open_order_dict):
        self._stored[open_order_dict["order_id"]] = dict(open_order_dict)

    def _update_open_order_as_dict(self, open_order_dict):
        self._stored[open_order_dict["order_id"]] = dict(open_order_dict)

    def _delete_open_order(self, order_id):
        del self._stored[order_id]

    def _get_all_open_orders(self):
        return [dict(stored) for stored in self._stored.values()]


class FakeDiagOverrides:
    def __init__(self, override):
        self._override = override

    def get_cumulative_override_for_instrument_strategy(self, instrument_strategy):
        return self._override


class FakeTradeLimits:
    def __init__(self, possible=999999):
        self._possible = possible
        self.added_trades = []

    def what_trade_qty_possible_for_instrument_strategy(
        self, instrument_strategy, proposed_trade_qty
    ):
        return self._possible

    @property
    def db_trade_limit_data(self):
        return self

    def add_trade(self, instrument_strategy, trade_qty):
        self.added_trades.append((str(instrument_strategy), trade_qty))


def make_placement(monkeypatch, override=DEFAULT_OVERRIDE, possible=999999, **kwargs):
    monkeypatch.setattr(
        placement_module, "diagOverrides", lambda data: FakeDiagOverrides(override)
    )
    monkeypatch.setattr(
        placement_module, "dataTradeLimits", lambda data: FakeTradeLimits(possible)
    )
    data = dataBlob(log_name="test_bybit_order_placement")
    api = kwargs.get("api", StubBybitAPI())
    open_orders_layer = kwargs.get("open_orders_layer", StubBybitOpenOrderData())
    placement = bybitOrderPlacement(data, api=api, open_orders_layer=open_orders_layer)
    return placement, open_orders_layer


def make_open_order(
    order_id="ORDER_1",
    instrument_code="LINK_BYBIT",
    symbol="LINK/USDT:USDT",
    side="buy",
    placed_datetime=None,
    attempts=0,
):
    if placed_datetime is None:
        placed_datetime = datetime.datetime.now() - datetime.timedelta(minutes=5)
    return bybitOpenOrder(
        order_id=order_id,
        instrument_code=instrument_code,
        symbol=symbol,
        side=side,
        qty_blocks=3,
        qty_coin=0.3,
        limit_price=100.0,
        placed_datetime=placed_datetime,
        attempts=attempts,
        status=STATUS_OPEN,
    )


def make_live_ready(monkeypatch):
    """
    Turn on live mode and stub the side-effects of a real fill/placement:
    the order-stack recording, price-limit recorder and position sync.
    Returns (limits, executed, synced) so tests can inspect what was recorded.
    """
    monkeypatch.setattr(
        placement_module.bybitOrderPlacement, "auto_trade_enabled", lambda self: True
    )
    limits = FakeTradeLimits()
    monkeypatch.setattr(placement_module, "dataTradeLimits", lambda data: limits)

    executed = []

    def fake_record_executed_trade_on_stack(
        data, instrument_code, filled_blocks, filled_price, commission=0.0
    ):
        executed.append((instrument_code, filled_blocks, filled_price, commission))

    monkeypatch.setattr(
        placement_module,
        "record_executed_trade_on_stack",
        fake_record_executed_trade_on_stack,
    )
    monkeypatch.setattr(
        placement_module,
        "filled_blocks_for_result",
        lambda result: abs(int(result["trade"]["qty_blocks"])),
    )

    synced = []
    monkeypatch.setattr(
        placement_module,
        "update_system_positions_from_bybit",
        lambda data: synced.append(data),
    )

    return limits, executed, synced


class TestOrderBook:
    def test_top_bid_and_ask(self):
        book = {"bids": [[100.0, 5], [99.0, 3]], "asks": [[100.5, 4], [101.0, 2]]}
        assert top_bid_from_order_book(book) == 100.0
        assert top_ask_from_order_book(book) == 100.5

    def test_empty_order_book_raises(self):
        with pytest.raises(Exception):
            top_bid_from_order_book({"asks": [[100.5, 4]]})
        with pytest.raises(Exception):
            top_ask_from_order_book({"bids": [[100.0, 5]]})

    def test_passive_limit_price_uses_book(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        assert placement.passive_limit_price("LINK/USDT:USDT", "buy") == 100.0
        assert placement.passive_limit_price("LINK/USDT:USDT", "sell") == 100.5


class TestPriceSanity:
    def test_price_within_limits(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        assert placement.price_within_limits(100.0, 100.0, 100.0)
        assert placement.price_within_limits(104.0, 100.0, 100.0)
        assert not placement.price_within_limits(106.0, 100.0, 100.0)

    def test_price_within_limits_falls_back_to_current_price(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        assert placement.price_within_limits(100.0, None, 100.0)

    def test_price_within_limits_rejects_zero_reference(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        assert not placement.price_within_limits(100.0, 0.0, 0.0)


class TestPlaceOneLimitOrder:
    def test_builds_open_order_record(self, monkeypatch):
        api = StubBybitAPI()
        placement, _ = make_placement(monkeypatch, api=api)

        trade = sample_trade(side="buy")
        placed = placement.place_one_limit_order(trade, 100.0)

        assert api.created_limit_orders == [("LINK/USDT:USDT", "buy", 0.3, 100.0)]
        assert placed.order_id == "LIMIT_1"
        assert placed.instrument_code == "LINK_BYBIT"
        assert placed.side == "buy"
        assert placed.qty_blocks == 3
        assert placed.qty_coin == 0.3
        assert placed.limit_price == 100.0
        assert placed.status == STATUS_OPEN
        assert placed.attempts == 0

    def test_rejects_amount_below_minimum(self, monkeypatch):
        api = StubBybitAPI(min_amount=1.0)
        placement, _ = make_placement(monkeypatch, api=api)

        with pytest.raises(Exception):
            placement.place_one_limit_order(sample_trade(), 100.0)

    def test_rejects_non_positive_amount(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        trade = sample_trade(qty_coin=0.0)
        with pytest.raises(Exception):
            placement.place_one_limit_order(trade, 100.0)


class TestDecideOrders:
    def test_places_orders_for_new_trades(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        open_instruments = []
        decisions = placement.decide_orders_from_plan(
            [sample_trade()], open_instruments
        )

        assert decisions[0]["action"] == ACTION_PLACE
        assert decisions[0]["limit_price"] == 100.0

    def test_skips_trade_when_open_order_exists(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        decisions = placement.decide_orders_from_plan([sample_trade()], ["LINK_BYBIT"])

        assert decisions[0]["action"] == ACTION_SKIP_EXISTS

    def test_skips_trade_when_no_trade_override(self, monkeypatch):
        placement, _ = make_placement(monkeypatch, override=NO_TRADE_OVERRIDE)
        decisions = placement.decide_orders_from_plan([sample_trade()], [])

        assert decisions[0]["action"] != ACTION_PLACE

    def test_skips_increasing_trade_when_reduce_only(self, monkeypatch):
        placement, _ = make_placement(monkeypatch, override=REDUCE_ONLY_OVERRIDE)
        decisions = placement.decide_orders_from_plan(
            [sample_trade(current_position=5, qty_blocks=3)], []
        )

        assert decisions[0]["action"] != ACTION_PLACE

    def test_allows_reducing_trade_when_reduce_only(self, monkeypatch):
        placement, _ = make_placement(monkeypatch, override=REDUCE_ONLY_OVERRIDE)
        decisions = placement.decide_orders_from_plan(
            [sample_trade(current_position=5, side="sell", qty_blocks=-3)], []
        )

        assert decisions[0]["action"] == ACTION_PLACE

    def test_skips_trade_when_trade_limit_reached(self, monkeypatch):
        placement, _ = make_placement(monkeypatch, possible=1)
        decisions = placement.decide_orders_from_plan([sample_trade()], [])

        assert decisions[0]["action"] != ACTION_PLACE

    def test_skips_trade_when_price_deviates(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        trade = sample_trade(price=130.0, current_price=130.0)
        decisions = placement.decide_orders_from_plan([trade], [])

        assert decisions[0]["action"] == ACTION_SKIP_PRICE

    def test_skips_trade_when_no_order_book(self, monkeypatch):
        api = StubBybitAPI(order_book={"bids": [], "asks": []})
        placement, _ = make_placement(monkeypatch, api=api)
        decisions = placement.decide_orders_from_plan([sample_trade()], [])

        assert decisions[0]["action"] == ACTION_SKIP_BOOK


class TestPlaceLimitOrders:
    def test_dry_run_places_nothing(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        monkeypatch.setattr(
            placement_module,
            "get_bybit_trade_plan",
            lambda data: [
                sample_trade(),
                sample_trade(instrument_code="BTC_BYBIT", symbol="BTC/USDT:USDT"),
            ],
        )
        placement.place_limit_orders()

        assert placement.api.created_limit_orders == []
        assert placement.open_orders.get_all_open_orders() == []

    def test_live_mode_places_and_records_orders(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        monkeypatch.setattr(
            placement_module,
            "get_bybit_trade_plan",
            lambda data: [sample_trade()],
        )
        monkeypatch.setattr(
            placement_module.bybitOrderPlacement,
            "auto_trade_enabled",
            lambda self: True,
        )

        placement.place_limit_orders()

        assert len(placement.api.created_limit_orders) == 1
        open_orders = placement.open_orders.get_all_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].instrument_code == "LINK_BYBIT"

    def test_live_mode_respects_existing_open_order(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        monkeypatch.setattr(
            placement_module,
            "get_bybit_trade_plan",
            lambda data: [sample_trade()],
        )
        monkeypatch.setattr(
            placement_module.bybitOrderPlacement,
            "auto_trade_enabled",
            lambda self: True,
        )

        placement.place_limit_orders()

        assert placement.api.created_limit_orders == []


class TestCheckOpenOrders:
    def test_dry_run_filled_order_not_recorded(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        placement.api._fetch_order_result = {
            "status": "closed",
            "filled": 0.3,
            "average": 100.0,
        }

        placement.check_open_orders()

        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None

    def test_stale_order_is_escalated_in_dry_run(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        old_datetime = datetime.datetime.now() - datetime.timedelta(hours=3)
        open_orders_layer.add_open_order(make_open_order(placed_datetime=old_datetime))
        placement.api._fetch_order_result = {
            "status": "open",
            "filled": 0.0,
            "average": None,
        }

        placement.check_open_orders()

        assert placement.api.cancelled_orders == []
        assert placement.api.created_market_orders == []

    def test_missing_exchange_order_does_not_remove_record(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())

        def raising_fetch_order(order_id, symbol):
            raise Exception("network error")

        monkeypatch.setattr(placement.api, "fetch_order", raising_fetch_order)

        placement.check_open_orders()

        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None

    def test_cancelled_on_exchange_escalated_in_dry_run(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        placement.api._fetch_order_result = {
            "status": "cancelled",
            "filled": 0.0,
            "average": None,
        }

        placement.check_open_orders()

        assert placement.api.created_market_orders == []


class TestCheckOpenOrdersLive:
    def test_live_filled_order_recorded_and_positions_synced(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        placement.api._fetch_order_result = {
            "status": "closed",
            "filled": 0.3,
            "average": 100.0,
        }
        limits, executed, synced = make_live_ready(monkeypatch)

        placement.check_open_orders()

        assert executed == [("LINK_BYBIT", 3, 100.0, 0.0)]
        assert limits.added_trades == [("bybit LINK_BYBIT", 3)]
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is None
        assert len(synced) == 1

    def test_live_cancelled_on_exchange_escalated_to_market(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        placement.api._fetch_order_result = {
            "status": "cancelled",
            "filled": 0.0,
            "average": None,
        }
        make_live_ready(monkeypatch)

        placement.check_open_orders()

        assert placement.api.cancelled_orders == []
        assert placement.api.created_market_orders == [("LINK/USDT:USDT", "buy", 0.3)]
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is None

    def test_live_stale_order_escalated_to_market(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        old_datetime = datetime.datetime.now() - datetime.timedelta(hours=3)
        open_orders_layer.add_open_order(make_open_order(placed_datetime=old_datetime))
        placement.api._fetch_order_result = {
            "status": "open",
            "filled": 0.0,
            "average": None,
        }
        make_live_ready(monkeypatch)

        placement.check_open_orders()

        assert placement.api.cancelled_orders == [("ORDER_1", "LINK/USDT:USDT")]
        assert placement.api.created_market_orders == [("LINK/USDT:USDT", "buy", 0.3)]
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is None


class TestHandleFilledOrder:
    def test_live_records_fill_on_stack_and_deletes_record(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        limits, executed, _ = make_live_ready(monkeypatch)

        placement.handle_filled_order(
            make_open_order(), {"status": "closed", "filled": 0.3, "average": 100.0}
        )

        assert executed == [("LINK_BYBIT", 3, 100.0, 0.0)]
        assert limits.added_trades == [("bybit LINK_BYBIT", 3)]
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is None

    def test_live_fill_with_no_quantity_keeps_record(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        monkeypatch.setattr(
            placement_module,
            "filled_blocks_for_result",
            lambda result: 0,
        )

        placement.handle_filled_order(
            make_open_order(), {"status": "closed", "filled": 0.0, "average": None}
        )

        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None

    def test_dry_run_fill_not_recorded(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        make_live_ready(monkeypatch)

        placement.handle_filled_order(
            make_open_order(),
            {"status": "closed", "filled": 0.3, "average": 100.0},
            dry_run=True,
        )

        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None


class TestEscalateToMarket:
    def test_live_cancels_limit_and_places_market_order(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        limits, executed, _ = make_live_ready(monkeypatch)

        placement.escalate_order_to_market(make_open_order())

        assert placement.api.cancelled_orders == [("ORDER_1", "LINK/USDT:USDT")]
        assert placement.api.created_market_orders == [("LINK/USDT:USDT", "buy", 0.3)]
        assert executed == [("LINK_BYBIT", 3, 100.0, 0.0)]
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is None

    def test_live_escalation_keeps_record_if_cancel_fails(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        make_live_ready(monkeypatch)
        monkeypatch.setattr(
            placement.api,
            "cancel_order",
            lambda order_id, symbol: (_ for _ in ()).throw(Exception("network error")),
        )

        placement.escalate_order_to_market(make_open_order())

        assert placement.api.created_market_orders == []
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None


class TestCancelOnCompletion:
    def test_dry_run_cancels_nothing(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())

        placement.cancel_open_orders_on_completion()

        assert placement.api.cancelled_orders == []
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None

    def test_live_cancels_all_open_orders(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        open_orders_layer.add_open_order(
            make_open_order(order_id="ORDER_2", symbol="BTC/USDT:USDT")
        )
        make_live_ready(monkeypatch)

        placement.cancel_open_orders_on_completion()

        assert placement.api.cancelled_orders == [
            ("ORDER_1", "LINK/USDT:USDT"),
            ("ORDER_2", "BTC/USDT:USDT"),
        ]
        assert placement.open_orders.get_all_open_orders() == []

    def test_live_cancel_disabled_leaves_orders(self, monkeypatch):
        placement, open_orders_layer = make_placement(monkeypatch)
        open_orders_layer.add_open_order(make_open_order())
        make_live_ready(monkeypatch)
        monkeypatch.setattr(
            placement_module.bybitOrderPlacement,
            "cancel_unfilled_at_end",
            property(lambda self: False),
        )

        placement.cancel_open_orders_on_completion()

        assert placement.api.cancelled_orders == []
        assert placement.open_orders.get_open_order_for_order_id("ORDER_1") is not None


class TestSyncPositions:
    def test_syncs_positions(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        synced = []
        monkeypatch.setattr(
            placement_module,
            "update_system_positions_from_bybit",
            lambda data: synced.append(data),
        )

        placement.sync_positions()

        assert len(synced) == 1

    def test_sync_failure_is_logged_not_raised(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)

        def failing_sync(data):
            raise Exception("boom")

        monkeypatch.setattr(
            placement_module, "update_system_positions_from_bybit", failing_sync
        )

        placement.sync_positions()


class TestOrderStaleness:
    def test_order_is_stale(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        old_order = make_open_order(
            placed_datetime=datetime.datetime.now() - datetime.timedelta(hours=2)
        )
        assert placement.order_is_stale(old_order, escalation_hours=1.0, max_attempts=4)

    def test_order_not_stale(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        fresh_order = make_open_order(
            placed_datetime=datetime.datetime.now() - datetime.timedelta(minutes=5)
        )
        assert not placement.order_is_stale(
            fresh_order, escalation_hours=1.0, max_attempts=4
        )

    def test_order_stale_when_attempts_exceeded(self, monkeypatch):
        placement, _ = make_placement(monkeypatch)
        fresh_order = make_open_order(attempts=5)
        assert placement.order_is_stale(
            fresh_order, escalation_hours=1.0, max_attempts=4
        )
