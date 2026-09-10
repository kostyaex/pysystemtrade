"""
Update the system position tables from the actual ByBit exchange positions.

Non-interactive equivalent of interactive_order_stack option 51: fetches the
current positions from the ByBit exchange (read-only API keys) and writes them
into the strategy / contract position tables as integer blocks.

Usage:
    python -m sysproduction.update_bybit_positions
"""

import logging

from sysdata.data_blob import dataBlob
from sysproduction.data.bybit_positions import update_system_positions_from_bybit
from syslogging.logger import get_logger

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("ccxt").setLevel(logging.WARNING)


def update_bybit_positions():
    log = get_logger("update_bybit_positions")
    with dataBlob(log_name="update_bybit_positions") as data:
        positions_blocks = update_system_positions_from_bybit(data)

        log.info("Fetched %d ByBit positions from exchange" % len(positions_blocks))
        for instrument_code, qty_blocks in sorted(positions_blocks.items()):
            log.info("%s: %d blocks" % (instrument_code, qty_blocks))

    return None


if __name__ == "__main__":
    update_bybit_positions()