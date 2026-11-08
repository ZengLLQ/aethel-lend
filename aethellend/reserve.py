"""Multi-asset reserve configuration and interest accrual."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .rate_model import KinkedInterestRateModel, RateParameters


SECONDS_PER_YEAR = 31536000.0


@dataclass
class ReserveConfig:
    """Configuration parameters for a collateral / borrow reserve."""
    asset: str
    loan_to_value: float = 0.75         # Maximum borrow ratio against this collateral (LTV)
    liquidation_threshold: float = 0.80  # Liquidation threshold (LT)
    liquidation_bonus: float = 0.05      # Liquidation penalty/bonus awarded to liquidators (5%)
    reserve_factor: float = 0.10         # Portion of interest directed to protocol reserves (10%)


class AssetReserve:
    """Tracks pool liquidity, cumulative borrow/supply indices, and protocol reserves."""

    def __init__(
        self,
        asset: str,
        config: Optional[ReserveConfig] = None,
        rate_model: Optional[KinkedInterestRateModel] = None,
        initial_timestamp: float = 0.0,
    ):
        self.asset = asset
        self.config = config or ReserveConfig(asset=asset)
        rate_params = RateParameters(reserve_factor=self.config.reserve_factor)
        self.rate_model = rate_model or KinkedInterestRateModel(rate_params)

        self.total_cash: float = 0.0
        self.total_borrows: float = 0.0
        self.total_reserves: float = 0.0

        self.borrow_index: float = 1.0
        self.supply_index: float = 1.0
        self.last_update_timestamp: float = initial_timestamp

    @property
    def total_liquidity(self) -> float:
        return self.total_cash + self.total_borrows

    @property
    def utilization_rate(self) -> float:
        return self.rate_model.get_utilization_rate(self.total_cash, self.total_borrows)

    @property
    def current_borrow_rate(self) -> float:
        return self.rate_model.get_borrow_rate(self.total_cash, self.total_borrows)

    @property
    def current_supply_rate(self) -> float:
        return self.rate_model.get_supply_rate(self.total_cash, self.total_borrows)

    def accrue_interest(self, current_timestamp: float) -> None:
        """Accrues compound interest based on elapsed time since last update."""
        if current_timestamp <= self.last_update_timestamp:
            return

        delta_t = (current_timestamp - self.last_update_timestamp) / SECONDS_PER_YEAR
        self.last_update_timestamp = current_timestamp

        if self.total_borrows <= 0.0:
            return

        borrow_rate = self.current_borrow_rate
        supply_rate = self.current_supply_rate

        interest_accumulated = self.total_borrows * borrow_rate * delta_t
        protocol_cut = interest_accumulated * self.config.reserve_factor

        self.total_borrows += interest_accumulated
        self.total_reserves += protocol_cut

        # Compound borrow index
        self.borrow_index *= (1.0 + borrow_rate * delta_t)

        # Compound supply index
        self.supply_index *= (1.0 + supply_rate * delta_t)
