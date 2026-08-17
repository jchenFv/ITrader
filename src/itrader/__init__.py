"""ITrader paper-trading agent."""

from .agent import TradingAgent
from .broker import SimulatedBroker
from .strategy import NewsMomentumStrategy, RiskConfig

__all__ = ["TradingAgent", "SimulatedBroker", "NewsMomentumStrategy", "RiskConfig"]
__version__ = "0.1.0"

