from sysdata.config.configdata import Config
from sysdata.sim.bybit_futures_sim_data import bybitFuturesSimData

from systems.forecasting import Rules
from systems.basesystem import System
from systems.forecast_combine import ForecastCombine
from systems.forecast_scale_cap import ForecastScaleCap
from systems.positionsizing import PositionSizing
from systems.portfolio import Portfolios
from systems.accounts.accounts_stage import Account
from systems.rawdata import RawData


def bybitsystem(data=None, config=None):
    """
    Example of how to 'wrap' a complete ByBit system
    """
    if config is None:
        config = Config("private.bybit.bybitconfig.yaml")
    if data is None:
        data = bybitFuturesSimData()

    my_system = System(
        [
            Account(),
            Portfolios(),
            PositionSizing(),
            ForecastCombine(),
            ForecastScaleCap(),
            Rules(),
            RawData(),
        ],
        data,
        config,
    )

    return my_system