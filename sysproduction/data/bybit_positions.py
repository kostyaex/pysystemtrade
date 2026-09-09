"""
Sync actual ByBit exchange positions into the system position tables.

Used in the manual ByBit trading mode: the user places orders on the ByBit
exchange directly, and this module pulls the resulting positions back into
pysystemtrade so that 'current' positions (shown e.g. by option 50 in the
interactive order stack) reflect reality.

Exchange positions are in base coins. They are converted to pysystemtrade
'blocks' using each instrument's Pointsize (= coins per block, see
data/futures/csvconfig/instrumentconfig.csv).
"""

from sysdata.data_blob import dataBlob

from sysdata.bybit.bybit_api import bybitAPI
from sysdata.bybit.bybit_multiple_prices import PERPETUAL_CONTRACT_DATE
from sysdata.csv.csv_instrument_data import csvFuturesInstrumentData
from sysdata.config.production_config import get_production_config
from sysdata.bybit.bybit_config import get_list_of_bybit_instruments

from sysobjects.contracts import futuresContract
from sysobjects.production.tradeable_object import instrumentStrategy

from sysproduction.data.positions import updatePositions

BYBIT_STRATEGY_NAME = "bybit"

KEYS_NOT_CONFIGURED_MESSAGE = """
ByBit API keys not configured.

Add to private/private_config.yaml:

  bybit_api_key: 'YOUR_API_KEY'
  bybit_api_secret: 'YOUR_API_SECRET'

Create the key pair on the ByBit website (Account -> API Management -> Create
New API key). Read-only keys are enough to fetch positions. The mobile app
does not support API key creation - use the web/desktop terminal.
"""


def get_bybit_coin_per_block(instrument_code: str) -> float:
    """
    Coins per block for a ByBit instrument, read from the CSV instrument
    config Pointsize column (e.g. BTC_BYBIT -> 0.001, LINK_BYBIT -> 0.1).
    """
    instrument_data = csvFuturesInstrumentData()
    meta_data = instrument_data.get_instrument_data(instrument_code).meta_data
    return float(meta_data.Pointsize)


def get_bybit_positions_from_exchange() -> dict:
    """
    Fetch current positions from the ByBit exchange.

    :return: dict of {instrument_code: signed_coin_qty}, e.g.
        {'LINK_BYBIT': 5.2, 'BTC_BYBIT': -0.001}
    :raises: Exception if API keys are not configured
    """
    bybit_api = bybitAPI()
    if not bybit_api.check_api_keys_present():
        raise Exception(KEYS_NOT_CONFIGURED_MESSAGE)

    return bybit_api.fetch_positions()


def exchange_positions_as_blocks(positions_coins: dict) -> dict:
    """
    Convert exchange positions in coins to integer positions in blocks.

    :param positions_coins: dict of {instrument_code: signed_coin_qty}
    :return: dict of {instrument_code: signed_block_qty}
    """
    positions_blocks = {}
    for instrument_code in get_list_of_bybit_instruments():
        qty_coins = positions_coins.get(instrument_code, 0.0)
        coin_per_block = get_bybit_coin_per_block(instrument_code)
        exact_blocks = qty_coins / coin_per_block
        qty_blocks = int(round(exact_blocks))

        if abs(exact_blocks - qty_blocks) > 0.001:
            print(
                "WARNING: %s qty %.6f coins is %.4f blocks (not a whole "
                "number) - rounded to %d blocks"
                % (instrument_code, qty_coins, exact_blocks, qty_blocks)
            )

        positions_blocks[instrument_code] = qty_blocks

    return positions_blocks


def update_system_positions_from_bybit(data: dataBlob) -> dict:
    """
    Fetch positions from the ByBit exchange and write them into the system
    strategy and contract position tables (price contract 20991200).

    :param data: data blob
    :return: dict of {instrument_code: signed_block_qty} written to the system
    """
    positions_coins = get_bybit_positions_from_exchange()
    positions_blocks = exchange_positions_as_blocks(positions_coins)

    update_positions_layer = updatePositions(data)

    for instrument_code, qty_blocks in sorted(positions_blocks.items()):
        instrument_strategy = instrumentStrategy(
            strategy_name=BYBIT_STRATEGY_NAME, instrument_code=instrument_code
        )
        update_positions_layer.db_strategy_position_data.update_position_for_instrument_strategy_object(
            instrument_strategy, qty_blocks
        )

        priced_contract = futuresContract(instrument_code, PERPETUAL_CONTRACT_DATE)
        update_positions_layer.db_contract_position_data.update_position_for_contract_object(
            priced_contract, qty_blocks
        )

    return positions_blocks
