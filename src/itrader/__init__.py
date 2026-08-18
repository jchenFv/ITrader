"""ITrader paper-trading agent."""

from .agent import TradingAgent
from .broker import SimulatedBroker
from .llm_strategy import LLMResearchStrategy
from .strategy import NewsMomentumStrategy, RiskConfig

__all__ = [
    "TradingAgent",
    "SimulatedBroker",
    "LLMResearchStrategy",
    "NewsMomentumStrategy",
    "RiskConfig",
]
__version__ = "0.2.0"
