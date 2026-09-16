"""
Shared daily ByBit maintenance tasks, exposed as processToRun timer methods.

Each method wraps a standalone module so every step of the old dagu
bybit_daily schedule (price update -> systems -> positions -> trade report ->
cache export) becomes a processToRun method driven by the pysystemtrade
scheduler instead of an external cron table.

Timer contract (see syscontrol.run_process): each entry in the runner's
list_of_timer_names_and_functions is a (method_name, object) tuple where the
object must expose the method as an attribute plus a ``data.log`` for
logging. ``bybitDailyTasks`` provides both.

The methods deliberately swallow exceptions and log them with ``log.critical``
instead of re-raising: if a timer method raises, the process exits without
being marked FINISHED in process control, which would block any downstream
process gated on it via ``process_configuration_previous_process``. Wrapping
keeps each step of the chain idempotent and self-contained.
"""

from sysdata.data_blob import dataBlob


class bybitDailyTasks(object):
    def __init__(self, data: dataBlob):
        self._data = data

    @property
    def data(self) -> dataBlob:
        return self._data

    @property
    def log(self):
        return self.data.log

    def update_bybit_prices(self):
        """Fetch fresh ByBit OHLCV + funding from the API into MongoDB."""
        from sysproduction.update_bybit_prices import update_bybit_prices

        try:
            update_bybit_prices()
        except Exception as exception:
            self.log.critical(
                "ByBit price update failed: %s" % str(exception),
                type="bybit_daily_tasks",
            )

    def update_system_positions(self):
        """Sync the system position tables from the actual ByBit positions."""
        from sysproduction.update_bybit_positions import update_bybit_positions

        try:
            update_bybit_positions()
        except Exception as exception:
            self.log.critical(
                "ByBit position sync failed: %s" % str(exception),
                type="bybit_daily_tasks",
            )

    def report_trades(self):
        """Report the recommended ByBit trades (optimal vs current positions)."""
        from sysproduction.report_bybit_recommended_trades import (
            report_bybit_recommended_trades,
        )

        try:
            report_bybit_recommended_trades()
        except Exception as exception:
            self.log.critical(
                "ByBit recommended trade report failed: %s" % str(exception),
                type="bybit_daily_tasks",
            )

    def export_cache(self):
        """Refresh the offline CSV cache (data/futures/bybit/) from MongoDB."""
        from sysinit.futures.bybit.export_bybit_cache_from_mongo import (
            export_bybit_cache,
        )

        try:
            export_bybit_cache()
        except Exception as exception:
            self.log.critical(
                "ByBit cache export failed: %s" % str(exception),
                type="bybit_daily_tasks",
            )
