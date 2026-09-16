"""
Automated placement of ByBit limit orders (logic behind the order placement
daemon sysproduction/run_bybit_order_placement.py).

The following methods are run on a timer by the daemon:

- place_limit_orders: for every instrument with a recommended trade (from the
    ByBit system's optimal positions) and no open limit order already, place a
    passive limit order at the best bid (buy) or best ask (sell). This is
    subject to: the bybit_auto_trade config flag (False means dry-run, we only
    log what we would send), overrides, trade limits, a price sanity check
    against the reference price, and the exchange minimum quantity.
- check_open_orders: reconcile open order records with the exchange. Filled
    orders are recorded on the order stack as balance trades (updating system
    positions). Unfilled orders that are too old (or have been checked too many
    times) are escalated to a market order; a limit order that has already
    disappeared from the exchange is also escalated.
- cancel_open_orders_on_completion: on process completion only, cancel any
    still-unfilled limit orders (config bybit_cancel_unfilled_orders_at_end,
    default True).

One open limit order per instrument is enforced through the open orders table
(MongoDB 'bybit_open_orders' collection in the default production database),
so repeated runs can never pile up duplicate orders for the same instrument.
"""

import datetime

from syscore.constants import arg_not_supplied
from syscore.genutils import str2Bool
from sysdata.data_blob import dataBlob
from sysdata.bybit.bybit_api import bybitAPI

from sysobjects.production.bybit_open_orders import (
    bybitOpenOrder,
    STATUS_OPEN,
)
from sysobjects.production.override import (
    NO_TRADE_OVERRIDE,
    REDUCE_ONLY_OVERRIDE,
)
from sysobjects.production.tradeable_object import instrumentStrategy

from sysproduction.data.bybit_orders import (
    BYBIT_STRATEGY_NAME,
    get_bybit_api_for_trading,
    get_bybit_trade_plan,
    record_executed_trade_on_stack,
    refresh_order_fill_details,
    filled_blocks_for_result,
    _commission_from_result,
    _is_nan,
)
from sysproduction.data.bybit_positions import update_system_positions_from_bybit
from sysproduction.data.bybit_open_orders import dataBybitOpenOrders
from sysproduction.data.controls import dataTradeLimits, diagOverrides

ACTION_PLACE = "place"
ACTION_SKIP_EXISTS = "skip_exists"
ACTION_SKIP_OVERRIDE = "skip_override"
ACTION_SKIP_LIMITS = "skip_limits"
ACTION_SKIP_PRICE = "skip_price"
ACTION_SKIP_BOOK = "skip_book"

ORDER_STATUS_CLOSED = "closed"
ORDER_STATUSES_CANCELLED = ("cancelled", "canceled", "rejected", "expired")

DEFAULT_LIMIT_ESCALATION_HOURS = 1.0
DEFAULT_LIMIT_ESCALATION_MAX_ATTEMPTS = 4
DEFAULT_PRICE_DEVIATION_PCT = 0.05
DEFAULT_CANCEL_UNFILLED_AT_END = True


class bybitOrderPlacement(object):
    def __init__(
        self,
        data: dataBlob,
        api=arg_not_supplied,
        open_orders_layer=arg_not_supplied,
    ):
        self._data = data

        if api is arg_not_supplied:
            api = get_bybit_api_for_trading(data.log)
        self._api = api

        if open_orders_layer is arg_not_supplied:
            open_orders_layer = dataBybitOpenOrders(data)
        self._open_orders = open_orders_layer

    @property
    def data(self) -> dataBlob:
        return self._data

    @property
    def log(self):
        return self.data.log

    @property
    def api(self) -> bybitAPI:
        return self._api

    @property
    def open_orders(self) -> dataBybitOpenOrders:
        return self._open_orders

    ##
    ## Timer methods run by the daemon
    ##

    def place_limit_orders(self):
        dry_run = not self.auto_trade_enabled()
        if dry_run:
            self.log.info(
                "ByBit auto trade DISABLED: dry run, nothing will be sent to the exchange"
            )

        trade_plan = get_bybit_trade_plan(self.data)
        if not trade_plan:
            self.log.info("No ByBit trades required")
            return None

        open_instruments = (
            self.open_orders.get_list_of_instrument_codes_with_open_orders()
        )
        decisions = self.decide_orders_from_plan(trade_plan, open_instruments)

        number_placed = 0
        for decision in decisions:
            trade = decision["trade"]
            instrument_code = trade["instrument_code"]
            action = decision["action"]

            if action != ACTION_PLACE:
                self.log.info(
                    "Skipping %s: %s" % (instrument_code, decision["skip_reason"])
                )
                continue

            limit_price = decision["limit_price"]
            if dry_run:
                self.log.info(
                    "DRY RUN: would place %s limit order for %s qty %.6f at %.2f"
                    % (
                        trade["side"].upper(),
                        instrument_code,
                        trade["qty_coin"],
                        limit_price,
                    )
                )
                continue

            try:
                placed_order = self.place_one_limit_order(trade, limit_price)
            except Exception as e:
                self.log.critical(
                    "Failed to place limit order for %s: %s" % (instrument_code, e)
                )
                continue

            self.open_orders.add_open_order(placed_order)
            number_placed += 1
            self.log.info(
                "Placed %s limit order for %s qty %.6f at %.2f (order id %s)"
                % (
                    trade["side"].upper(),
                    instrument_code,
                    placed_order.qty_coin,
                    placed_order.limit_price,
                    placed_order.order_id,
                )
            )

        if dry_run:
            self.log.info(
                "ByBit dry run: %d orders would have been placed" % number_placed
            )
        else:
            self.log.info("ByBit limit orders placed: %d" % number_placed)

        return None

    def check_open_orders(self):
        dry_run = not self.auto_trade_enabled()
        open_orders = self.open_orders.get_all_open_orders()
        if len(open_orders) == 0:
            return None

        escalation_hours = self.limit_escalation_hours()
        max_attempts = self.limit_escalation_max_attempts()
        instruments_filled = []

        for open_order in open_orders:
            try:
                exchange_order = self.api.fetch_order(
                    open_order.order_id, open_order.symbol
                )
            except Exception as e:
                self.log.error(
                    "Couldn't fetch open order %s for %s: %s"
                    % (open_order.order_id, open_order.instrument_code, e)
                )
                continue

            status = exchange_order.get("status")
            filled_coin = float(exchange_order.get("filled") or 0.0)

            if filled_coin > 0 or status == ORDER_STATUS_CLOSED:
                self.handle_filled_order(open_order, exchange_order, dry_run=dry_run)
                if not dry_run:
                    instruments_filled.append(open_order.instrument_code)
                continue

            if status in ORDER_STATUSES_CANCELLED:
                self.log.warning(
                    "Open order record %s for %s is %s on the exchange; escalating to a market order"
                    % (open_order.order_id, open_order.instrument_code, status)
                )
                self.escalate_order_to_market(
                    open_order, dry_run=dry_run, order_already_cancelled=True
                )
                continue

            ## Still open on the exchange
            if self.order_is_stale(open_order, escalation_hours, max_attempts):
                self.log.critical(
                    "Limit order %s for %s has not filled after %.1f hours / %d attempts; escalating to a market order"
                    % (
                        open_order.order_id,
                        open_order.instrument_code,
                        escalation_hours,
                        max_attempts,
                    )
                )
                self.escalate_order_to_market(open_order, dry_run=dry_run)
            else:
                self.log.debug(
                    "Limit order %s for %s still open"
                    % (open_order.order_id, open_order.instrument_code)
                )
                self.increment_attempts(open_order)

        if instruments_filled:
            self.sync_positions()

        return None

    def cancel_open_orders_on_completion(self):
        dry_run = not self.auto_trade_enabled()
        if dry_run:
            self.log.info(
                "ByBit auto trade DISABLED: not cancelling any orders on completion (dry run)"
            )
            return None

        if not self.cancel_unfilled_at_end:
            self.log.info(
                "bybit_cancel_unfilled_orders_at_end is False: leaving unfilled limit orders on the exchange"
            )
            return None

        open_orders = self.open_orders.get_all_open_orders()
        if len(open_orders) == 0:
            self.log.info("No open ByBit orders to cancel at end of process")
            return None

        for open_order in open_orders:
            try:
                self.api.cancel_order(open_order.order_id, open_order.symbol)
            except Exception as e:
                self.log.critical(
                    "Couldn't cancel unfilled ByBit order %s for %s: %s"
                    % (open_order.order_id, open_order.instrument_code, e)
                )
                continue

            self.open_orders.delete_open_order(open_order.order_id)
            self.log.info(
                "Cancelled unfilled ByBit order %s for %s at end of process"
                % (open_order.order_id, open_order.instrument_code)
            )

        return None

    ##
    ## Decision logic
    ##

    def decide_orders_from_plan(self, trade_plan: list, open_instruments: list) -> list:
        decisions = []
        for trade in trade_plan:
            instrument_code = trade["instrument_code"]

            if instrument_code in open_instruments:
                decisions.append(
                    self._skip_decision(
                        trade, ACTION_SKIP_EXISTS, "already has an open limit order"
                    )
                )
                continue

            allowed, reason = self.check_override_allows_trade(
                instrument_code, trade["qty_blocks"], trade["current_position_blocks"]
            )
            if not allowed:
                decisions.append(
                    self._skip_decision(trade, ACTION_SKIP_OVERRIDE, reason)
                )
                continue

            allowed, reason = self.check_trade_limits_allow_trade(
                instrument_code, trade["qty_blocks"]
            )
            if not allowed:
                decisions.append(self._skip_decision(trade, ACTION_SKIP_LIMITS, reason))
                continue

            try:
                limit_price = self.passive_limit_price(trade["symbol"], trade["side"])
            except Exception as e:
                decisions.append(
                    self._skip_decision(
                        trade, ACTION_SKIP_BOOK, "no order book: %s" % e
                    )
                )
                continue

            if not self.price_within_limits(
                limit_price, trade["reference_price"], trade["current_price"]
            ):
                decisions.append(
                    self._skip_decision(
                        trade,
                        ACTION_SKIP_PRICE,
                        "limit price %.6f deviates too much from reference price"
                        % limit_price,
                    )
                )
                continue

            decisions.append(
                {
                    "trade": trade,
                    "action": ACTION_PLACE,
                    "limit_price": limit_price,
                    "skip_reason": "",
                }
            )

        return decisions

    def check_override_allows_trade(
        self, instrument_code: str, qty_blocks, current_position_blocks
    ):
        instrument_strategy = instrumentStrategy(BYBIT_STRATEGY_NAME, instrument_code)
        override = diagOverrides(
            self.data
        ).get_cumulative_override_for_instrument_strategy(instrument_strategy)

        if override == NO_TRADE_OVERRIDE:
            return False, "no trade override on %s" % instrument_code

        if override == REDUCE_ONLY_OVERRIDE:
            current_position = int(current_position_blocks)
            proposed_trade = int(qty_blocks)
            new_position_abs = abs(current_position + proposed_trade)
            current_position_abs = abs(current_position)
            if new_position_abs >= current_position_abs:
                return (
                    False,
                    "reduce only override on %s (trade would not reduce position)"
                    % instrument_code,
                )

        return True, ""

    def check_trade_limits_allow_trade(self, instrument_code: str, qty_blocks):
        instrument_strategy = instrumentStrategy(BYBIT_STRATEGY_NAME, instrument_code)
        trade_limits = dataTradeLimits(self.data)
        proposed_trade_qty = abs(int(qty_blocks))
        possible_trade = trade_limits.what_trade_qty_possible_for_instrument_strategy(
            instrument_strategy, proposed_trade_qty
        )
        if possible_trade < proposed_trade_qty:
            return False, "trade limit reached for %s (%d of %d blocks possible)" % (
                instrument_code,
                possible_trade,
                proposed_trade_qty,
            )

        return True, ""

    def passive_limit_price(self, symbol: str, side: str) -> float:
        order_book = self.api.fetch_order_book(symbol)
        if side == "buy":
            return top_bid_from_order_book(order_book)
        elif side == "sell":
            return top_ask_from_order_book(order_book)
        else:
            raise Exception("Don't know what to do with side %s" % side)

    def price_within_limits(
        self, limit_price: float, reference_price, current_price: float
    ) -> bool:
        reference = reference_price
        if reference is None or _is_nan(reference):
            reference = current_price
        if reference is None or _is_nan(reference) or float(reference) <= 0:
            return False

        deviation = abs(float(limit_price) - float(reference)) / float(reference)

        return deviation <= self.price_deviation_pct()

    ##
    ## Order execution
    ##

    def place_one_limit_order(self, trade: dict, limit_price: float) -> bybitOpenOrder:
        symbol = trade["symbol"]
        side = trade["side"]
        amount = float(trade["qty_coin"])

        if amount <= 0:
            raise Exception("Invalid amount %s for %s" % (amount, symbol))

        min_amount = self.api.get_min_order_amount(symbol)
        if min_amount > 0 and amount < min_amount:
            raise Exception(
                "Amount %s below exchange minimum %s for %s"
                % (amount, min_amount, symbol)
            )

        limit_price = self.api.get_price_precision(symbol, limit_price)
        order = self.api.create_limit_order(symbol, side, amount, limit_price)
        order_id = order.get("id")
        if not order_id:
            raise Exception("No order id returned for %s" % symbol)

        return bybitOpenOrder(
            order_id=order_id,
            instrument_code=trade["instrument_code"],
            symbol=symbol,
            side=side,
            qty_blocks=int(trade["qty_blocks"]),
            qty_coin=amount,
            limit_price=float(limit_price),
            placed_datetime=datetime.datetime.now(),
            attempts=0,
            status=STATUS_OPEN,
        )

    def handle_filled_order(self, open_order, exchange_order, dry_run: bool = False):
        if dry_run:
            self.log.info(
                "DRY RUN: would record fill for %s order %s as filled"
                % (open_order.instrument_code, open_order.order_id)
            )
            return None

        result = self._result_from_exchange_order(open_order, exchange_order)
        filled_blocks = filled_blocks_for_result(result)
        if filled_blocks == 0:
            self.log.error(
                "Order %s for %s reported filled but no fill quantity; leaving record to re-check"
                % (open_order.order_id, open_order.instrument_code)
            )
            return None

        commission = _commission_from_result(result)
        record_executed_trade_on_stack(
            self.data,
            open_order.instrument_code,
            filled_blocks,
            result["filled_price"],
            commission=commission,
        )

        instrument_strategy = instrumentStrategy(
            BYBIT_STRATEGY_NAME, open_order.instrument_code
        )
        trade_limits = dataTradeLimits(self.data)
        trade_limits.db_trade_limit_data.add_trade(
            instrument_strategy, abs(filled_blocks)
        )

        self.open_orders.delete_open_order(open_order.order_id)
        self.log.info(
            "Recorded ByBit fill %s for %s (%d blocks)"
            % (open_order.order_id, open_order.instrument_code, filled_blocks)
        )

        return None

    def escalate_order_to_market(
        self, open_order, dry_run: bool = False, order_already_cancelled: bool = False
    ):
        if dry_run:
            self.log.info(
                "DRY RUN: would cancel order %s and escalate %s to a market order"
                % (open_order.order_id, open_order.instrument_code)
            )
            return None

        if not order_already_cancelled:
            try:
                self.api.cancel_order(open_order.order_id, open_order.symbol)
            except Exception as e:
                ## We can't confirm the limit order is gone, don't add a market
                ## order on top of it: leave the record and re-try next cycle.
                self.log.critical(
                    "Can't cancel limit order %s for %s (%s); not escalating so no duplicate risk, will re-try next cycle"
                    % (open_order.order_id, open_order.instrument_code, e)
                )
                return None

        try:
            exchange_order = self.api.create_market_order(
                open_order.symbol, open_order.side, open_order.qty_coin
            )
        except Exception as e:
            self.log.critical(
                "Failed to place market order for %s: %s; leaving limit order record"
                % (open_order.instrument_code, e)
            )
            return None

        exchange_order = refresh_order_fill_details(
            self.api, exchange_order, open_order.symbol, open_order.limit_price
        )
        self.handle_filled_order(open_order, exchange_order)

        return None

    def increment_attempts(self, open_order):
        open_order.attempts = open_order.attempts + 1
        self.open_orders.update_open_order(open_order)

    def order_is_stale(
        self, open_order, escalation_hours: float, max_attempts: int
    ) -> bool:
        age_hours = (
            datetime.datetime.now() - open_order.placed_datetime
        ).total_seconds() / 3600.0
        if age_hours >= escalation_hours:
            return True
        if open_order.attempts >= max_attempts:
            return True

        return False

    def sync_positions(self):
        try:
            update_system_positions_from_bybit(self.data)
        except Exception as e:
            self.log.error("Couldn't sync ByBit positions: %s" % e)

    ##
    ## Config helpers
    ##

    def auto_trade_enabled(self) -> bool:
        return self._config_bool("bybit_auto_trade", False)

    def limit_escalation_hours(self) -> float:
        return self._config_float(
            "bybit_limit_escalation_hours", DEFAULT_LIMIT_ESCALATION_HOURS
        )

    def limit_escalation_max_attempts(self) -> int:
        return self._config_int(
            "bybit_limit_escalation_max_attempts", DEFAULT_LIMIT_ESCALATION_MAX_ATTEMPTS
        )

    def price_deviation_pct(self) -> float:
        return self._config_float(
            "bybit_price_deviation_pct", DEFAULT_PRICE_DEVIATION_PCT
        )

    @property
    def cancel_unfilled_at_end(self) -> bool:
        return self._config_bool(
            "bybit_cancel_unfilled_orders_at_end", DEFAULT_CANCEL_UNFILLED_AT_END
        )

    def _config_bool(self, element_name: str, default: bool) -> bool:
        value = self.data.config.get_element_or_default(element_name, default)
        return str2Bool(value)

    def _config_float(self, element_name: str, default: float) -> float:
        value = self.data.config.get_element_or_default(element_name, default)
        return float(value)

    def _config_int(self, element_name: str, default: int) -> int:
        value = self.data.config.get_element_or_default(element_name, default)
        return int(value)

    def _skip_decision(self, trade, action: str, skip_reason: str) -> dict:
        return {
            "trade": trade,
            "action": action,
            "limit_price": None,
            "skip_reason": skip_reason,
        }

    def _result_from_exchange_order(self, open_order, exchange_order) -> dict:
        return {
            "trade": {
                "instrument_code": open_order.instrument_code,
                "side": open_order.side,
                "qty_blocks": open_order.qty_blocks,
            },
            "status": exchange_order.get("status"),
            "order_id": open_order.order_id,
            "filled_coin": float(exchange_order.get("filled") or 0.0),
            "filled_price": float(
                exchange_order.get("average") or open_order.limit_price or 0.0
            ),
            "order": exchange_order,
        }


def top_bid_from_order_book(order_book: dict) -> float:
    bids = order_book.get("bids") or []
    if len(bids) == 0:
        raise Exception("No bids in order book")
    return float(bids[0][0])


def top_ask_from_order_book(order_book: dict) -> float:
    asks = order_book.get("asks") or []
    if len(asks) == 0:
        raise Exception("No asks in order book")
    return float(asks[0][0])
