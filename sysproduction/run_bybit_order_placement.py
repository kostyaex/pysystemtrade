"""
Run the ByBit order placement daemon.

Periodically places passive limit orders for the recommended ByBit trades,
monitors their fills and escalates unfilled limit orders to market orders. The
actual logic lives in sysproduction/bybit_order_placement.py.

Follows the run_stack_handler pattern: a processToRun wraps a list of
timer-class methods whose frequency and other parameters are configured in
private_control_config.yaml (process_configuration_methods:
run_bybit_order_placement). The process must also be registered there and
started from the crontab.

With bybit_auto_trade: false (the default) the daemon only logs what it would
do and never sends anything to the exchange.
"""

from syscontrol.run_process import processToRun
from sysdata.data_blob import dataBlob

from sysproduction.bybit_order_placement import bybitOrderPlacement


def run_bybit_order_placement():
    process_name = "run_bybit_order_placement"
    data = dataBlob(log_name=process_name)
    placement_object = bybitOrderPlacement(data)
    list_of_timer_names_and_functions = [
        ("place_limit_orders", placement_object),
        ("check_open_orders", placement_object),
        ("cancel_open_orders_on_completion", placement_object),
    ]
    price_process = processToRun(process_name, data, list_of_timer_names_and_functions)
    price_process.run_process()


if __name__ == "__main__":
    run_bybit_order_placement()
