"""Custom exception types for the trading bot."""


class TradingBotError(Exception):
    """Base error for the bot."""


class BrokerError(TradingBotError):
    """Anything broker / exchange related."""


class InsufficientCapitalError(TradingBotError):
    """Raised when calculated lot can't be opened with available margin."""


class RiskViolationError(TradingBotError):
    """Raised when a trade would violate the risk policy."""


class ConfigurationError(TradingBotError):
    """Invalid configuration."""


class DataError(TradingBotError):
    """Market data missing or corrupt."""
