from syscore.dateutils import Frequency, MIXED_FREQ
from sysdata.futures.futures_per_contract_prices import futuresContractPriceData
from sysobjects.futures_per_contract_prices import futuresContractPrices
from sysobjects.contracts import futuresContract, listOfFuturesContracts
from sysdata.bybit.bybit_api import bybitAPI
from syscore.constants import arg_not_supplied
from syslogging.logger import *

PERPETUAL_CONTRACT_DATE = "20991200"


class bybitFuturesContractPriceData(futuresContractPriceData):
    """
    Read and write contract price data for ByBit perpetual contracts.

    Perpetuals have no expiry, so we use a synthetic contract date of 20991200.
    Data is fetched from ByBit API on demand.
    """

    def __init__(
        self,
        bybit_api: bybitAPI = arg_not_supplied,
        log=get_logger("bybitFuturesContractPriceData"),
    ):
        super().__init__(log=log)
        if bybit_api is arg_not_supplied:
            bybit_api = bybitAPI(log=log)
        self._bybit_api = bybit_api

    def __repr__(self):
        return "bybitFuturesContractPriceData using ByBit API"

    @property
    def bybit_api(self) -> bybitAPI:
        return self._bybit_api

    def has_merged_price_data_for_contract(
        self, futures_contract: futuresContract
    ) -> bool:
        if futures_contract.date_str == PERPETUAL_CONTRACT_DATE:
            return True
        return False

    def get_contracts_with_merged_price_data(self) -> listOfFuturesContracts:
        return listOfFuturesContracts([])

    def get_contracts_with_price_data_for_frequency(
        self, frequency: Frequency
    ) -> listOfFuturesContracts:
        return listOfFuturesContracts([])

    def _get_merged_prices_for_contract_object_no_checking(
        self, futures_contract_object: futuresContract
    ) -> futuresContractPrices:
        return self._get_prices_from_bybit(futures_contract_object)

    def _get_prices_at_frequency_for_contract_object_no_checking(
        self, futures_contract_object: futuresContract, frequency: Frequency
    ) -> futuresContractPrices:
        return self._get_prices_from_bybit(futures_contract_object)

    def _get_prices_from_bybit(
        self, futures_contract_object: futuresContract
    ) -> futuresContractPrices:
        instrument_code = futures_contract_object.instrument_code
        symbol = self.bybit_api.instrument_code_to_bybit_symbol(instrument_code)

        self.log.info(
            "Fetching contract prices for %s (ByBit symbol: %s)"
            % (instrument_code, symbol),
            instrument_code=instrument_code,
        )

        ohlcv = self.bybit_api.fetch_ohlcv_all(symbol, timeframe="1d")

        if len(ohlcv) == 0:
            self.log.warning(
                "No OHLCV data returned for %s" % instrument_code,
                instrument_code=instrument_code,
            )
            return futuresContractPrices.create_empty()

        return futuresContractPrices(ohlcv)

    def _write_merged_prices_for_contract_object_no_checking(
        self,
        futures_contract_object: futuresContract,
        futures_price_data: futuresContractPrices,
    ):
        self.log.info(
            "ByBit contract prices are fetched from API - nothing to write locally",
            instrument_code=futures_contract_object.instrument_code,
        )

    def _write_prices_at_frequency_for_contract_object_no_checking(
        self,
        futures_contract_object: futuresContract,
        futures_price_data: futuresContractPrices,
        frequency: Frequency,
    ):
        self.log.info(
            "ByBit contract prices are fetched from API - nothing to write locally",
            instrument_code=futures_contract_object.instrument_code,
        )

    def _delete_merged_prices_for_contract_object_with_no_checks_be_careful(
        self, futures_contract_object: futuresContract
    ):
        self.log.info(
            "ByBit contract prices are fetched from API - nothing to delete locally",
            instrument_code=futures_contract_object.instrument_code,
        )

    def _delete_prices_at_frequency_for_contract_object_with_no_checks_be_careful(
        self, futures_contract_object: futuresContract, frequency: Frequency
    ):
        self.log.info(
            "ByBit contract prices are fetched from API - nothing to delete locally",
            instrument_code=futures_contract_object.instrument_code,
        )
