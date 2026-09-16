"""
Record of a ByBit limit order placed (but not yet filled) by the automated
order placement daemon (sysproduction/run_bybit_order_placement.py).

The exchange order id is the unique key. Records are removed once the order
has filled, been cancelled, or been escalated to a market order.
"""

import datetime
from dataclasses import dataclass

STATUS_OPEN = "OPEN"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_ESCALATED = "ESCALATED"

ORDER_ID_KEY = "order_id"


@dataclass
class bybitOpenOrder:
    order_id: str
    instrument_code: str
    symbol: str
    side: str
    qty_blocks: int
    qty_coin: float
    limit_price: float
    placed_datetime: datetime.datetime
    attempts: int
    status: str

    @property
    def signed_qty_blocks(self) -> int:
        if self.side == "sell":
            return -abs(self.qty_blocks)
        return abs(self.qty_blocks)

    def as_dict(self) -> dict:
        return {
            ORDER_ID_KEY: self.order_id,
            "instrument_code": self.instrument_code,
            "symbol": self.symbol,
            "side": self.side,
            "qty_blocks": self.qty_blocks,
            "qty_coin": self.qty_coin,
            "limit_price": self.limit_price,
            "placed_datetime": self.placed_datetime.isoformat(),
            "attempts": self.attempts,
            "status": self.status,
        }

    @classmethod
    def from_dict(bybitOpenOrder, attr_dict):
        return bybitOpenOrder(
            order_id=attr_dict[ORDER_ID_KEY],
            instrument_code=attr_dict["instrument_code"],
            symbol=attr_dict["symbol"],
            side=attr_dict["side"],
            qty_blocks=int(attr_dict["qty_blocks"]),
            qty_coin=float(attr_dict["qty_coin"]),
            limit_price=float(attr_dict["limit_price"]),
            placed_datetime=datetime.datetime.fromisoformat(
                attr_dict["placed_datetime"]
            ),
            attempts=int(attr_dict.get("attempts", 0)),
            status=attr_dict.get("status", STATUS_OPEN),
        )


class listOfBybitOpenOrders(list):
    def get_list_of_instrument_codes(self) -> list:
        return list(set([order.instrument_code for order in self]))

    def for_instrument(self, instrument_code: str):
        orders_with_instrument = [
            order for order in self if order.instrument_code == instrument_code
        ]
        return listOfBybitOpenOrders(orders_with_instrument)

    def order_for_instrument(self, instrument_code: str):
        orders_with_instrument = self.for_instrument(instrument_code)
        if len(orders_with_instrument) == 0:
            return None
        return orders_with_instrument[0]
