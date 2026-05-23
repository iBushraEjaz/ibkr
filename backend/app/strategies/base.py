from abc import ABC, abstractmethod


class Strategy(ABC):
    """
    Base class for all trading strategies.
    Each strategy manages one symbol and receives tick events from the bot loop.
    """

    @abstractmethod
    async def start(self) -> None:
        """Called once when the bot starts. Set up subscriptions and schedules here."""

    @abstractmethod
    def on_tick(self, ticker) -> None:
        """Called on every market data tick for this symbol."""

    @abstractmethod
    def cleanup(self) -> None:
        """Called on bot shutdown. Cancel orders and unsubscribe market data."""

    @property
    @abstractmethod
    def state(self) -> str:
        """Return current state: idle | watching | order_placed | in_position | done"""
