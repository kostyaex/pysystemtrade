from sysdata.csv.csv_instrument_data import (
    csvFuturesInstrumentData,
    INSTRUMENT_CONFIG_PATH,
)
from syscore.constants import arg_not_supplied

BYBIT_SUFFIX = "_BYBIT"


def get_list_of_bybit_instruments(
    instrument_data: csvFuturesInstrumentData = arg_not_supplied,
) -> list:
    """
    Get the list of ByBit instruments from the CSV instrument config.

    Only instruments whose code ends with '_BYBIT' are considered ByBit instruments.
    """
    if instrument_data is arg_not_supplied:
        instrument_data = csvFuturesInstrumentData()

    all_instruments = instrument_data.get_list_of_instruments()
    bybit_instruments = [i for i in all_instruments if i.endswith(BYBIT_SUFFIX)]

    return bybit_instruments
