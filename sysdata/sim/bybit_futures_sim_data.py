from syscore.constants import arg_not_supplied
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.csv.csv_roll_parameters import csvRollParametersData
from sysdata.csv.csv_spread_costs import csvSpreadCostData
from sysdata.bybit.bybit_adjusted_prices import bybitFuturesAdjustedPricesData
from sysdata.bybit.bybit_multiple_prices import bybitFuturesMultiplePricesData
from sysdata.bybit.bybit_fx_prices import bybitFxPricesData
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from sysdata.data_blob import dataBlob
from sysdata.sim.futures_sim_data_with_data_blob import genericBlobUsingFuturesSimData
from syslogging.logger import *


class bybitFuturesSimData(genericBlobUsingFuturesSimData):
    """
    SimData for ByBit perpetual futures.

    Uses ByBit API for price data (adjusted, multiple, FX).
    Uses CSV for instrument config, roll parameters, and spread costs.
    """

    def __init__(
        self,
        data: dataBlob = arg_not_supplied,
        bybit_api: bybitAPI = arg_not_supplied,
        log=get_logger("bybitFuturesSimData"),
    ):
        if data is arg_not_supplied:
            if bybit_api is arg_not_supplied:
                bybit_api = bybitAPI(log=log)

            data = dataBlob(
                log=log,
                class_list=[
                    bybitFuturesAdjustedPricesData,
                    bybitFuturesMultiplePricesData,
                    bybitFxPricesData,
                    csvFuturesInstrumentData,
                    csvRollParametersData,
                    csvSpreadCostData,
                ],
            )

        super().__init__(data=data)

    def __repr__(self):
        return "bybitFuturesSimData object with %d instruments" % len(
            self.get_instrument_list()
        )

    def get_instrument_list(self):
        return get_list_of_bybit_instruments()
