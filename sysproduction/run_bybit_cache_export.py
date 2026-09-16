"""
Run the daily ByBit CSV cache export as a processToRun.

Refreshes the offline backtest cache (data/futures/bybit/) from MongoDB. No
ByBit API calls are made. The actual work lives in
sysproduction/bybit_daily_tasks.py (class bybitDailyTasks, method
export_cache).

Follows the run_stack_handler pattern: a processToRun wraps a single timer
method whose frequency / max_executions live in the control config
(default or private override). The process must be registered there and kicked
daily (systemd timer / crontab). Once the method has run once the process marks
itself FINISHED in process control.
"""

from syscontrol.run_process import processToRun
from sysdata.data_blob import dataBlob

from sysproduction.bybit_daily_tasks import bybitDailyTasks


def run_bybit_cache_export():
    process_name = "run_bybit_cache_export"
    data = dataBlob(log_name=process_name)
    tasks_object = bybitDailyTasks(data)
    list_of_timer_names_and_functions = [
        ("export_cache", tasks_object),
    ]
    cache_process = processToRun(process_name, data, list_of_timer_names_and_functions)
    cache_process.run_process()


if __name__ == "__main__":
    run_bybit_cache_export()
