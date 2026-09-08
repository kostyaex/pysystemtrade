"""
ByBit perpetual futures strategy runner.

- Gets capital from the database (earmarked with a strategy name)
- Runs a backtest using ByBit MongoDB data
- Writes optimal (buffered) positions into the database

Usage in private/control_config.yaml:

  process_configuration_methods:
    run_systems:
      bybit:
        max_executions: 1
        object: sysproduction.strategy_code.run_bybit_system.runBybitSystem
        backtest_config_filename: private/bybit/bybitconfig.yaml
"""

from syscore.constants import arg_not_supplied

from sysdata.data_blob import dataBlob
from sysdata.sim.bybit_futures_sim_data import bybitFuturesSimData, DATA_SOURCE_MONGO

from systems.provided.futures_chapter15.basesystem import futures_system
from systems.basesystem import System

from sysproduction.strategy_code.run_system_classic import (
    runSystemClassic,
    updated_buffered_positions,
)


class runBybitSystem(runSystemClassic):
    """
    Strategy runner for ByBit perpetual futures.

    Inherits from runSystemClassic. The only difference is system_method:
    it builds a System using bybitFuturesSimData (MongoDB-backed) instead
    of the default IB/Arctic production data.

    The ByBit Mongo reader classes are registered on the shared data blob
    (just as get_sim_data_object_for_production does for the standard data),
    so that updated_buffered_positions -> dataContracts(data) can resolve the
    priced (perpetual) contract id.
    """

    @property
    def function_to_call_on_update(self):
        return updated_buffered_positions

    def system_method(
        self,
        notional_trading_capital: float = arg_not_supplied,
        base_currency: str = arg_not_supplied,
    ) -> System:
        data = self.data
        backtest_config_filename = self.backtest_config_filename

        system = production_bybit_system(
            data,
            backtest_config_filename,
            log=data.log,
            notional_trading_capital=notional_trading_capital,
            base_currency=base_currency,
        )

        return system


def production_bybit_system(
    data: dataBlob,
    config_filename: str,
    log=None,
    notional_trading_capital: float = arg_not_supplied,
    base_currency: str = arg_not_supplied,
) -> System:
    from syslogging.logger import get_logger

    if log is None:
        log = get_logger("bybit_system")

    sim_data = make_bybit_production_sim_data(data, log=log)

    from sysdata.config.configdata import Config

    config = Config(config_filename)

    if notional_trading_capital is not arg_not_supplied:
        config.notional_trading_capital = notional_trading_capital

    if base_currency is not arg_not_supplied:
        config.base_currency = base_currency

    system = futures_system(data=sim_data, config=config)
    system._log = log

    return system


def make_bybit_production_sim_data(data: dataBlob, log=None):
    """
    Build a MongoDB-backed ByBit sim data.

    The ByBit Mongo reader classes are injected onto the shared `data` blob
    (aliased as db_futures_adjusted_prices / db_futures_multiple_prices /
    db_fx_prices) so that both the System and downstream helpers that read
    from `data` (e.g. dataContracts in updated_buffered_positions) can resolve
    the required data.

    Returns a bybitFuturesSimData wired to that Mongo-backed data.
    """
    from sysdata.bybit.bybit_adjusted_prices import bybitFuturesAdjustedPricesData
    from sysdata.bybit.bybit_multiple_prices import bybitFuturesMultiplePricesData
    from sysdata.bybit.bybit_fx_prices import bybitFxPricesData
    from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
    from sysdata.csv.csv_roll_parameters import csvRollParametersData
    from sysdata.csv.csv_spread_costs import csvSpreadCostData

    if log is None:
        from syslogging.logger import get_logger

        log = get_logger("bybit_system")

    data.add_class_list(
        [
            bybitFuturesAdjustedPricesData,
            bybitFuturesMultiplePricesData,
            bybitFxPricesData,
            csvFuturesInstrumentData,
            csvRollParametersData,
            csvSpreadCostData,
        ]
    )

    sim_data = bybitFuturesSimData(
        data=data,
        data_source=DATA_SOURCE_MONGO,
        log=log,
    )

    return sim_data
