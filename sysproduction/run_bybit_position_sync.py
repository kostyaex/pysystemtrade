"""
Run the daily ByBit position sync as a processToRun.

Fetches the current positions from the ByBit exchange and writes them into the
system position tables as integer blocks. The actual work lives in
sysproduction/bybit_daily_tasks.py (class bybitDailyTasks, method
update_system_positions).

Follows the run_stack_handler pattern: a processToRun wraps a single timer
method whose frequency / max_executions live in the control config
(default or private override). The process must be registered there and kicked
daily (systemd timer / crontab). Once the method has run once the process marks
itself FINISHED in process control.
"""

from syscontrol.run_process import processToRun
from sysdata.data_blob import dataBlob

from sysproduction.bybit_daily_tasks import bybitDailyTasks


def run_bybit_position_sync():
    process_name = "run_bybit_position_sync"
    data = dataBlob(log_name=process_name)
    tasks_object = bybitDailyTasks(data)
    list_of_timer_names_and_functions = [
        ("update_system_positions", tasks_object),
    ]
    position_process = processToRun(
        process_name, data, list_of_timer_names_and_functions
    )
    position_process.run_process()


if __name__ == "__main__":
    run_bybit_position_sync()
