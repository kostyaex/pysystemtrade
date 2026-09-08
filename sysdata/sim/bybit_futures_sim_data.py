from syscore.constants import arg_not_supplied
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.csv.csv_roll_parameters import csvRollParametersData
from sysdata.csv.csv_spread_costs import csvSpreadCostData
from sysdata.bybit.bybit_adjusted_prices import bybitFuturesAdjustedPricesData
from sysdata.bybit.bybit_multiple_prices import bybitFuturesMultiplePricesData
from sysdata.bybit.bybit_fx_prices import bybitFxPricesData
from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_mongo_api import bybitMongoAPI
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments
from sysdata.data_blob import dataBlob
from sysdata.sim.futures_sim_data_with_data_blob import genericBlobUsingFuturesSimData
from syslogging.logger import *

DATA_SOURCE_API = "api"
DATA_SOURCE_MONGO = "mongo"


def make_bybit_api_from_data_source(data_source: str, log):
    if data_source == DATA_SOURCE_API:
        return bybitAPI(log=log)
    elif data_source == DATA_SOURCE_MONGO:
        return bybitMongoAPI(log=log)
    else:
        raise Exception(
            "data_source '%s' not recognised, must be '%s' or '%s'"
            % (data_source, DATA_SOURCE_API, DATA_SOURCE_MONGO)
        )


class bybitFuturesSimData(genericBlobUsingFuturesSimData):
    """
    SimData for ByBit perpetual futures.

    Uses ByBit API for price data (adjusted, multiple, FX) when
    data_source='api' (default, backtest path). When data_source='mongo' the
    same data is read from MongoDB (db 'bybit'), populated by the production
    updater `sysproduction/update_bybit_prices.py`.
    Uses CSV for instrument config, roll parameters, and spread costs.
    """

    def __init__(
        self,
        data: dataBlob = arg_not_supplied,
        bybit_api: bybitAPI = arg_not_supplied,
        data_source: str = DATA_SOURCE_API,
        log=get_logger("bybitFuturesSimData"),
    ):
        if data is arg_not_supplied:
            if bybit_api is arg_not_supplied:
                bybit_api = make_bybit_api_from_data_source(data_source, log)

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

            if data_source == DATA_SOURCE_MONGO:
                # Replace the default live-API readers with the Mongo-backed
                # source: optionally-injected bybit_api wins, otherwise uses
                # the Mongo-based data source built above.
                data.db_futures_adjusted_prices = bybitFuturesAdjustedPricesData(
                    bybit_api=bybit_api, log=log
                )
                data.db_futures_multiple_prices = bybitFuturesMultiplePricesData(
                    bybit_api=bybit_api, log=log
                )
                data.db_fx_prices = bybitFxPricesData(bybit_api=bybit_api, log=log)

        super().__init__(data=data)

    def __repr__(self):
        return "bybitFuturesSimData object with %d instruments" % len(
            self.get_instrument_list()
        )

    def get_instrument_list(self):
        return get_list_of_bybit_instruments()
