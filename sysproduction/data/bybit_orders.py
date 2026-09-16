"""
Execute ByBit trades with two-step manual confirmation.

The system computes the recommended trades (optimal buffered position vs current
exchange position), the user reviews them with live prices, confirms each order
individually, and only then are orders placed on the ByBit exchange via ccxt.

Market orders that fill immediately are recorded on the order stack as balance
trades (instrument -> contract -> broker), which also updates the system
position tables. Limit orders are placed and their exchange order id is shown;
the user can sync positions once they fill (interactive option 51).

Used in the manual ByBit trading mode. Nothing is sent to the exchange without
an explicit per-order confirmation.
"""

import datetime
import math

from sysdata.data_blob import dataBlob
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_contract_prices import PERPETUAL_CONTRACT_DATE

from syscore.constants import arg_not_supplied
from syscore.interactive.input import get_input_from_user_and_convert_to_type

from sysproduction.report_bybit_recommended_trades import bybit_recommended_trades_table
from sysproduction.data.bybit_positions import (
    get_bybit_coin_per_block,
    update_system_positions_from_bybit,
    KEYS_NOT_CONFIGURED_MESSAGE,
)

from sysexecution.stack_handler.balance_trades import stackHandlerCreateBalanceTrades
from sysexecution.orders.broker_orders import (
    brokerOrder,
    balance_order_type as broker_balance_order_type,
)

BYBIT_STRATEGY_NAME = "bybit"

ORDER_TYPE_MARKET = "market"
ORDER_TYPE_LIMIT = "limit"

ACTION_EXECUTE = "execute"
ACTION_SKIP = "skip"
ACTION_QUIT = "quit"


def get_bybit_api_for_trading(log=arg_not_supplied) -> bybitAPI:
    """
    Build a ByBit API instance with the keys required for order placement.
    """
    if log is arg_not_supplied:
        from syslogging.logger import get_logger

        log = get_logger("bybit_orders")

    api = bybitAPI(log=log)
    if not api.check_api_keys_present():
        raise Exception(KEYS_NOT_CONFIGURED_MESSAGE)

    return api


def get_bybit_trade_plan(data: dataBlob) -> list:
    """
    Compute the recommended ByBit trades enriched with live prices.

    :return: list of trade dicts, empty if no trades needed
    """
    display_df = bybit_recommended_trades_table(data)[0]
    if display_df is None:
        return []

    api = get_bybit_api_for_trading(data.log)

    trade_plan = []
    for trade_key, row in display_df.iterrows():
        instrument_code = trade_key.split(" ")[-1]
        trade_blocks = int(row["blk"])
        if trade_blocks == 0:
            continue

        symbol = api.instrument_code_to_bybit_symbol(instrument_code)
        current_price = get_current_price_from_ticker(api, symbol)

        if trade_blocks > 0:
            side = "buy"
        else:
            side = "sell"

        qty_coin = abs(float(row["qty_coin"]))
        reference_price = (
            float(row["price"]) if not _is_nan(row["price"]) else current_price
        )

        trade_plan.append(
            {
                "instrument_code": instrument_code,
                "symbol": symbol,
                "side": side,
                "qty_blocks": trade_blocks,
                "qty_coin": qty_coin,
                "current_position_blocks": int(row["current"]),
                "current_price": current_price,
                "reference_price": reference_price,
                "notional_usd": qty_coin * current_price,
                "order_type": ORDER_TYPE_MARKET,
                "limit_price": None,
            }
        )

    return trade_plan


def _is_nan(value) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def get_current_price_from_ticker(api: bybitAPI, symbol: str) -> float:
    """
    Get the current mid-ish price for a symbol, preferring the last trade price
    then bid then ask. Returns 0.0 if the exchange returns nothing usable.
    """
    try:
        ticker = api.fetch_ticker(symbol)
    except Exception:
        return 0.0

    for key in ("last", "bid", "ask"):
        value = ticker.get(key)
        if value:
            return float(value)

    return 0.0


def display_trade_plan(trade_plan: list):
    print("\n=== ByBit trade plan (review) ===\n")
    print(
        "%-10s %5s %6s %14s %14s %12s %8s"
        % ("Instrument", "Side", "Blk", "Qty coin", "Price", "Notional US$", "Cur pos")
    )
    for trade in trade_plan:
        print(
            "%-10s %5s %6d %14.6f %14.2f %12.2f %8d"
            % (
                trade["instrument_code"],
                trade["side"].upper(),
                trade["qty_blocks"],
                trade["qty_coin"],
                trade["current_price"],
                trade["notional_usd"],
                trade["current_position_blocks"],
            )
        )
    print(
        "\nQuantity is in base coins (1 block = %s coins); prices in USDT."
        % _describe_one_block(trade_plan)
    )


def _describe_one_block(trade_plan: list) -> str:
    try:
        instrument_code = trade_plan[0]["instrument_code"]
        return "{:.10g}".format(get_bybit_coin_per_block(instrument_code))
    except Exception:
        return "coin_per_block"


def confirm_and_execute_trades(data: dataBlob, trade_plan: list) -> list:
    """
    Walk through each recommended trade and ask the user how to proceed.

    :return: list of execution result dicts for trades that were placed
    """
    api = get_bybit_api_for_trading(data.log)

    results = []
    total = len(trade_plan)
    for index, trade in enumerate(trade_plan):
        decision = get_execution_decision_for_trade(trade, index, total)

        action = decision["action"]
        if action == ACTION_QUIT:
            print("Quitting. Remaining trades not executed.")
            break
        if action == ACTION_SKIP:
            print("Skipping %s." % trade["instrument_code"])
            continue

        trade["order_type"] = decision["order_type"]
        trade["limit_price"] = decision["limit_price"]

        try:
            result = execute_trade_on_bybit(api, trade)
        except Exception as e:
            # If we can't be sure the order went through, stop and let the user
            # investigate rather than placing any more trades blindly.
            print("ERROR executing %s: %s" % (trade["instrument_code"], e))
            print("Aborting remaining trades to let you investigate.")
            break

        results.append(result)

    return results


def get_execution_decision_for_trade(trade: dict, index: int, total: int) -> dict:
    """
    Show one recommended trade and ask the user whether to execute it and how.

    :return: dict with 'action' one of execute/skip/quit; if execute, also
        'order_type' and 'limit_price'
    """
    print("\n--- Trade %d of %d ---" % (index + 1, total))
    print("Instrument : %s" % trade["instrument_code"])
    print("Side       : %s" % trade["side"].upper())
    print(
        "Quantity   : %14.6f %s (%d blocks)"
        % (
            trade["qty_coin"],
            trade["instrument_code"].replace("_BYBIT", ""),
            trade["qty_blocks"],
        )
    )
    print("Price      : %14.2f USDT" % trade["current_price"])
    print("Notional   : %12.2f US$" % trade["notional_usd"])
    print("Position   : currently %d blocks" % trade["current_position_blocks"])

    while True:
        response = input("Execute as [m]arket / [l]imit / [s]kip / [q]uit? ")
        if response == "":
            continue
        first = response[0].lower()
        if first == "m":
            return {
                "action": ACTION_EXECUTE,
                "order_type": ORDER_TYPE_MARKET,
                "limit_price": None,
            }
        if first == "l":
            limit_price = get_input_from_user_and_convert_to_type(
                "Limit price (USDT)", float, allow_default=False
            )
            return {
                "action": ACTION_EXECUTE,
                "order_type": ORDER_TYPE_LIMIT,
                "limit_price": limit_price,
            }
        if first == "s":
            return {"action": ACTION_SKIP}
        if first == "q":
            return {"action": ACTION_QUIT}

        print("Need one of m/l/s/q")


def execute_trade_on_bybit(api: bybitAPI, trade: dict) -> dict:
    """
    Place a single order on ByBit, with quantity safety checks.

    :return: result dict with trade, status, order_id, filled_coin, filled_price
    """
    symbol = trade["symbol"]
    side = trade["side"]
    amount = trade["qty_coin"]

    if amount <= 0:
        raise Exception("Invalid amount %s for %s" % (amount, symbol))

    min_amount = api.get_min_order_amount(symbol)
    if min_amount > 0 and amount < min_amount:
        print(
            "WARNING: %s amount %s is below the exchange minimum %s; skipping"
            % (symbol, amount, min_amount)
        )
        return {
            "trade": trade,
            "status": "skipped_below_min",
            "order_id": None,
            "filled_coin": 0.0,
            "filled_price": 0.0,
        }

    if trade["order_type"] == ORDER_TYPE_MARKET:
        order = api.create_market_order(symbol, side, amount)
        order = refresh_order_fill_details(api, order, symbol, trade["current_price"])
    else:
        # A limit order is expected to stay open; its fill will be confirmed
        # later once the user syncs positions (option 51). No fetch needed now.
        order = api.create_limit_order(symbol, side, amount, trade["limit_price"])

    return {
        "trade": trade,
        "status": order.get("status"),
        "order_id": order.get("id"),
        "filled_coin": float(order.get("filled") or 0.0),
        "filled_price": float(order.get("average") or trade["current_price"] or 0.0),
        "order": order,
    }


def refresh_order_fill_details(
    api: bybitAPI, order: dict, symbol: str, fallback_price: float
) -> dict:
    """
    The create-order response on ByBit is often minimal. If we can't see a fill
    yet for a just-executed order, ask the exchange for its current state.

    :param order: unified ccxt order dict as returned by create_market_order
    :param symbol: trading pair, e.g. 'LINK/USDT:USDT'
    :param fallback_price: price to use if no average fill price is available
    :return: enriched order dict
    """
    filled = float(order.get("filled") or 0.0)
    average = float(order.get("average") or 0.0)

    if filled > 0 and average > 0:
        return order

    order_id = order.get("id")
    if not order_id:
        return order

    try:
        refreshed = api.fetch_order(order_id, symbol)
    except Exception:
        return order

    if refreshed is None:
        return order

    if (
        float(refreshed.get("filled") or 0.0) > 0
        or float(refreshed.get("average") or 0.0) > 0
    ):
        return refreshed

    # keep the fill fields from the original response
    return order


def filled_blocks_for_result(result: dict) -> int:
    """
    Convert an executed coin fill into signed blocks for the order stack.

    :return: signed number of blocks filled, 0 if nothing filled
    """
    filled_coin = result.get("filled_coin", 0.0)
    if filled_coin <= 0:
        return 0

    instrument_code = result["trade"]["instrument_code"]
    coin_per_block = get_bybit_coin_per_block(instrument_code)
    if coin_per_block <= 0:
        return 0

    exact_blocks = filled_coin / coin_per_block
    blocks = int(round(exact_blocks))

    if result["trade"]["side"] == "sell":
        blocks = -blocks

    return blocks


def record_executed_trade_on_stack(
    data: dataBlob,
    instrument_code: str,
    qty_blocks: int,
    filled_price: float,
    commission: float = 0.0,
):
    """
    Record an executed ByBit trade on the order stack as a balance trade
    (instrument -> contract -> broker, pre-filled, inactive), which also
    updates the system position tables.

    :param qty_blocks: signed number of blocks actually filled
    """
    if qty_blocks == 0:
        return None

    broker_order = brokerOrder(
        BYBIT_STRATEGY_NAME,
        instrument_code,
        PERPETUAL_CONTRACT_DATE,
        qty_blocks,
        fill=qty_blocks,
        algo_used="bybit_market",
        order_type=broker_balance_order_type,
        filled_price=filled_price,
        fill_datetime=datetime.datetime.now(),
        broker_account="ByBit",
        commission=commission,
        manual_fill=True,
        active=False,
    )

    stack_handler = stackHandlerCreateBalanceTrades(data)
    stack_handler.create_balance_trade(broker_order)


def execute_bybit_trades(data: dataBlob):
    """
    Main entry point (interactive_order_stack option 52): compute the
    recommended trades, show them with live prices, confirm each one, place the
    confirmed orders on ByBit, record fills on the stack, and sync positions.
    """
    print("\n=== Execute ByBit trades ===\n")

    trade_plan = get_bybit_trade_plan(data)
    if not trade_plan:
        print("No ByBit trades required (positions within buffer).")
        return None

    display_trade_plan(trade_plan)
    print("\nNothing has been sent to the exchange yet.")
    proceed = get_input_from_user_and_convert_to_type(
        "Type 'go' to begin per-order confirmation",
        str,
        allow_default=False,
        check_type=False,
    )
    if proceed.strip().lower() != "go":
        print("Aborted. No orders placed.")
        return None

    results = confirm_and_execute_trades(data, trade_plan)
    if not results:
        print("\nNo trades executed.")
        return None

    _record_filled_market_orders(data, results)

    _print_execution_summary(results)

    print("\nSyncing positions from exchange...")
    try:
        update_system_positions_from_bybit(data)
        print("Positions synced. Re-run option 50 to see the new state.")
    except Exception as e:
        print("Could not sync positions: %s" % e)

    return None


def _record_filled_market_orders(data: dataBlob, results: list):
    for result in results:
        trade = result["trade"]
        if trade["order_type"] != ORDER_TYPE_MARKET:
            continue

        filled_blocks = filled_blocks_for_result(result)
        if filled_blocks == 0:
            print(
                "WARNING: %s market order not filled (status %s); not recorded on stack"
                % (trade["instrument_code"], result["status"])
            )
            continue

        if abs(filled_blocks) != abs(trade["qty_blocks"]):
            print(
                "WARNING: %s partially filled: %d of %d blocks; recording the partial fill"
                % (trade["instrument_code"], filled_blocks, trade["qty_blocks"])
            )

        commission = _commission_from_result(result)
        record_executed_trade_on_stack(
            data,
            trade["instrument_code"],
            filled_blocks,
            result["filled_price"],
            commission=commission,
        )


def _commission_from_result(result: dict) -> float:
    order = result.get("order")
    if order is None:
        return 0.0
    fee = order.get("fee") or {}
    try:
        return float(fee.get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _print_execution_summary(results: list):
    print("\n=== Execution summary ===")
    for result in results:
        trade = result["trade"]
        instrument_code = trade["instrument_code"]
        order_id = result["order_id"]

        if trade["order_type"] == ORDER_TYPE_MARKET:
            filled = result["filled_coin"]
            price = result["filled_price"]
            print(
                "%s market %s filled %s coins at %s (exchange order id %s)"
                % (instrument_code, trade["side"].upper(), filled, price, order_id)
            )
        else:
            print(
                "%s limit %s placed at %s, exchange order id %s. "
                "Track it on ByBit; sync positions with option 51 once it fills."
                % (
                    instrument_code,
                    trade["side"].upper(),
                    trade.get("limit_price"),
                    order_id,
                )
            )

    return None
