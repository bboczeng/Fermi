from enum import Enum
from datetime import datetime
from collections import OrderedDict
from sortedcontainers import SortedDict
import uuid

import time

_PREC = 8
_PPREC = 2


class OrderSide(Enum):
    Buy = "buy"
    Sell = "sell"


class OrderType(Enum):
    Limit = "limit"
    Market = "market"
    StopLimit = "stop_limit"


class OrderStatus(Enum):
    Submitted = "submitted"
    Accepted = "accepted"
    Open = "open"
    Filled = "filled"
    Cancelled = "cancelled"


class Transaction(object):
    def __init__(self, quote_name: str, base_name: str, price: float, amount: float, side: OrderSide,
                 timestamp: int):
        self._timestamp = timestamp
        self._datetime = datetime.fromtimestamp(timestamp / 1000.0)
        self._side = side
        self._quote_name = quote_name
        self._base_name = base_name
        self._symbol = quote_name + "/" + base_name
        self._amount = amount
        self._price = price
        self._id = self._generate_unique_id()

    def _generate_unique_id(self) -> int:
        # should be unique, datetime + name
        return int(uuid.uuid4().hex, 16)

    @property
    def timestamp(self) -> int:
        return self._timestamp

    @property
    def datetime(self) -> datetime:
        return self._datetime

    @property
    def side(self) -> OrderSide:
        return self._side

    @property
    def quote_name(self) -> str:
        return self._quote_name

    @property
    def base_name(self) -> str:
        return self._base_name

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def amount(self) -> float:
        return self._amount

    @property
    def price(self) -> float:
        return self._price

    @property
    def id(self) -> int:
        return self._id

    @property
    def info(self) -> dict:
        return {'datetime': str(self.datetime), 'timestamp': self.timestamp, 'price': round(self.price, _PREC),
                'amount': round(self.amount, _PREC)}


class Order(Transaction):
    def __init__(self, timestamp: int, order_type: OrderType, side: OrderSide, quote_name: str, base_name: str,
                 amount: float, price: float, stop_price: float):
        assert amount > 0
        # follow the convention of ccxt
        if order_type is OrderType.Market:
            price = 0
        if order_type is not OrderType.StopLimit:
            stop_price = 0
        assert price >= 0 and stop_price >= 0

        super(Order, self).__init__(quote_name, base_name, price, amount, side, timestamp)

        self._status = OrderStatus.Submitted
        self._type = order_type
        self._stop_price = stop_price
        self._filled = 0
        self._transactions = []
        self._fee = {}

    @property
    def status(self) -> OrderStatus:
        return self._status

    @property
    def type(self) -> OrderType:
        return self._type

    @property
    def filled(self) -> float:
        return self._filled

    @property
    def filled_percentage(self) -> float:
        return round((self._filled / self._amount) * 100.0, _PPREC)

    @property
    def stop_price(self) -> float:
        return self._stop_price

    @property
    def remaining(self) -> float:
        return self.amount - self.filled

    @property
    def transactions(self) -> list:
        return self._transactions

    @property
    def fee(self) -> dict:
        return self._fee

    @property
    def info(self) -> dict:
        return {'id': self.id, 'datetime': str(self.datetime), 'timestamp': self.timestamp, 'status': self.status.value,
                'symbol': self.symbol, 'type': self.type.value, 'side': self.side.value,
                'price': round(self.price, _PREC), 'stop_price': round(self.stop_price, _PREC),
                'amount': round(self.amount, _PREC), 'filled': round(self.filled, _PREC),
                'remaining': round(self.remaining, _PREC), 'transaction': [tx.info for tx in self._transactions],
                'fee': {a: round(self.fee[a], _PREC) for a in self.fee}}

    def open(self):
        assert self.type is not OrderType.Market
        self._status = OrderStatus.Open

    def accept(self):
        assert self.type is OrderType.StopLimit
        self._status = OrderStatus.Accepted

    def cancel(self):
        self._status = OrderStatus.Cancelled

    def generate_transaction(self, amount: float, price: float, timestamp: int) -> Transaction:
        return Transaction(quote_name=self.quote_name,
                           base_name=self.base_name,
                           price=price,
                           amount=amount,
                           side=self.side,
                           timestamp=timestamp)

    def execute_transaction(self, transaction: Transaction) -> bool:
        """
        Returns:
             A bool indicates whether the order is filled or not.
        """
        assert isinstance(transaction, Transaction), "type must be transaction"

        if transaction.side == OrderSide.Buy:
            self._filled += transaction.amount
            self.transactions.append(transaction)
        else:
            self._filled += transaction.amount
            self.transactions.append(transaction)

        assert self.amount - self.filled >= 0

        if self.amount - self.filled == 0:
            self._status = OrderStatus.Filled
            return True
        else:
            return False

    def pay_fee(self, asset: str, amount: float):
        if amount == 0:
            return
        if asset not in self.fee:
            self._fee[asset] = amount
        else:
            self._fee[asset] += amount


class OrderBookBase(object):
    def __init__(self):
        self.book = {}

    def __iter__(self):
        return iter(self.book.values())

    def __getitem__(self, order_id: str) -> Order:
        return self.get_order(order_id)

    def __len__(self):
        return len(self.book)

    def get_order(self, order_id: str) -> Order:
        return self.book[order_id]


class OrderQueue(OrderBookBase):
    def __init__(self):
        super(OrderQueue, self).__init__()
        self.book = OrderedDict()

    def add_new_order(self, timestamp, order_type, side, quote_name, base_name, amount, price, stop_price):
        new_order = Order(timestamp=timestamp, order_type=order_type, side=side, quote_name=quote_name,
                          base_name=base_name, amount=amount, price=price, stop_price=stop_price)
        self.book[new_order.id] = new_order
        return new_order.id

    def pop_order(self) -> Order:
        return self.book.popitem(last=False)[1]

    def get_orders(self, limit: int=0, id_only=True) -> list:
        orders = []
        count = 0
        for order_id, order in list(self.book.items()):
            if id_only:
                orders.append(order_id)
            else:
                orders.append(order.info)
            count += 1
            if count == limit > 0:
                break
        return orders


class OrderBook(OrderBookBase):
    def __init__(self):
        super(OrderBook, self).__init__()
        self.time_dict = SortedDict(lambda order_id: self.book[order_id].timestamp)
        self.symbol_dict = {}

    def insert_order(self, order: Order):
        order_id = order.id

        self.book[order_id] = order
        self.time_dict[order_id] = order
        symbol = order.symbol
        if symbol not in self.symbol_dict:
            self.symbol_dict[symbol] = SortedDict(lambda o_id: self.book[o_id].timestamp)
            self.symbol_dict[symbol][order_id] = order
        else:
            self.symbol_dict[symbol][order_id] = order

    def remove_order(self, order: Order):
        del self.time_dict[order.id]
        del self.symbol_dict[order.symbol][order.id]
        del self.book[order.id]  # must delete this last. otherwise key lambda can't be executed

    def get_orders(self, symbol: str='', limit: int=0, id_only=True) -> list:
        if symbol == '':
            if limit <= 0:
                order_list = list(self.time_dict.keys())
            else:
                limit = min(limit, len(self.book))
                order_list = self.time_dict.iloc[-limit:]
        elif symbol not in self.symbol_dict:
            return []
        else:
            if limit <= 0:
                order_list = list(self.symbol_dict[symbol].keys())
            else:
                limit = min(limit, len(self.symbol_dict[symbol]))
                order_list = self.symbol_dict[symbol].iloc[-limit:]

        if not id_only:
            orders = []
            for order_id in order_list:
                orders.append(self.book[order_id].info)
            return orders

        return order_list
