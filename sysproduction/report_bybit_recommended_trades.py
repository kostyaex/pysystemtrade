"""
Report the recommended ByBit trades (optimal vs current positions).

Non-interactive equivalent of interactive_order_stack option 50: computes, for
every ByBit instrument, the position break between the optimal (buffered)
position produced by run_systems and the current position synced from the
exchange, and logs the blocks / coins to trade.

Usage:
    python -m sysproduction.report_bybit_recommended_trades
"""

import logging

import pandas as pd

from sysdata.data_blob import dataBlob
from sysproduction.data.bybit_positions import get_bybit_coin_per_block
from sysproduction.data.optimal_positions import dataOptimalPositions
from syslogging.logger import get_logger

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("ccxt").setLevel(logging.WARNING)

BYBIT_INSTRUMENT_SUFFIX = "_BYBIT"


def _required_position_given_buffered(optimal_position, current_position: float) -> float:
    if not hasattr(optimal_position, "lower_position"):
        return current_position

    lower = optimal_position.lower_position
    upper = optimal_position.upper_position

    if current_position < lower:
        return round(lower)
    elif current_position > upper:
        return round(upper)
    else:
        return current_position


def bybit_recommended_trades_table(data: dataBlob):
    """
    Compute the recommended ByBit trades.

    :param data: data blob
    :return: tuple of (display_df, has_breaks); display_df is None if there are
        no ByBit optimal positions stored (run run_systems first).
    """
    data_optimal = dataOptimalPositions(data)
    breaks_df = data_optimal.get_pd_of_position_breaks()

    bybit_mask = breaks_df.index.str.contains(BYBIT_INSTRUMENT_SUFFIX)
    bybit_df = breaks_df[bybit_mask]

    if len(bybit_df) == 0:
        return None, False

    bybit_df = bybit_df.copy()

    bybit_df["lower"] = [
        opt.lower_position if hasattr(opt, "lower_position") else float("nan")
        for opt in bybit_df["optimal"]
    ]
    bybit_df["upper"] = [
        opt.upper_position if hasattr(opt, "upper_position") else float("nan")
        for opt in bybit_df["optimal"]
    ]
    bybit_df["required"] = [
        _required_position_given_buffered(opt, current)
        for opt, current in zip(bybit_df["optimal"], bybit_df["current"])
    ]
    bybit_df["trade"] = (
        (bybit_df["required"] - bybit_df["current"].astype(float)).round(0).astype(int)
    )
    bybit_df["coin_per_block"] = [
        get_bybit_coin_per_block(instrument_code)
        for instrument_code in [key.split(" ")[-1] for key in bybit_df.index]
    ]
    bybit_df["qty_coin"] = [
        round(trade * cpb, 4)
        for trade, cpb in zip(bybit_df["trade"], bybit_df["coin_per_block"])
    ]
    bybit_df["reference_price"] = [
        opt.reference_price if hasattr(opt, "reference_price") else float("nan")
        for opt in bybit_df["optimal"]
    ]
    bybit_df["notional_usd"] = [
        round(qty * price, 2)
        for qty, price in zip(bybit_df["qty_coin"], bybit_df["reference_price"])
    ]

    display_df = bybit_df[
        [
            "current",
            "lower",
            "upper",
            "required",
            "trade",
            "qty_coin",
            "reference_price",
            "notional_usd",
            "breaks",
        ]
    ]
    display_df.columns = [
        "current",
        "lower",
        "upper",
        "req",
        "blk",
        "qty_coin",
        "price",
        "notional_USD",
        "breaks",
    ]
    has_breaks = bool(bybit_df["breaks"].any())

    return display_df, has_breaks


def report_bybit_recommended_trades():
    log = get_logger("report_bybit_recommended_trades")
    with dataBlob(log_name="report_bybit_recommended_trades") as data:
        display_df, has_breaks = bybit_recommended_trades_table(data)

        if display_df is None:
            log.critical("No ByBit optimal positions found: run run_systems first")
            raise Exception("No ByBit optimal positions found: run run_systems first")

        print(display_df.to_string())
        print(
            "\nColumns: current/lower/upper/req in blocks (1 block = "
            "coin_per_block coins on ByBit);"
        )
        print(
            "blk = blocks to trade; qty_coin = order quantity in coins; "
            "notional_USD = qty_coin x reference price."
        )

        if has_breaks:
            log.info("Some instruments have position breaks - trades needed")
        else:
            log.info("All ByBit positions within buffer - no trades needed")

    return None


if __name__ == "__main__":
    report_bybit_recommended_trades()