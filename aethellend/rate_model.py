"""Dynamic piecewise linear (kinked) interest rate model."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RateParameters:
    """Interest rate model hyperparameters."""
    base_rate: float = 0.02           # 2% APR at U = 0
    multiplier: float = 0.08          # 8% APR slope up to optimal kink
    jump_multiplier: float = 1.20     # Steep 120% APR slope past optimal kink
    optimal_utilization: float = 0.80 # 80% optimal utilization threshold
    reserve_factor: float = 0.10      # 10% fee retained by protocol reserves


class KinkedInterestRateModel:
    """Computes variable borrowing and lending rates as a function of capital utilization."""

    def __init__(self, params: RateParameters | None = None):
        self.params = params or RateParameters()

    def get_utilization_rate(self, total_cash: float, total_borrows: float) -> float:
        """Utilization U = Borrows / (Cash + Borrows)."""
        total_liquidity = total_cash + total_borrows
        if total_liquidity <= 0.0:
            return 0.0
        return min(1.0, max(0.0, total_borrows / total_liquidity))

    def get_borrow_rate(self, total_cash: float, total_borrows: float) -> float:
        r"""Calculates instantaneous annual borrowing interest rate:

        If U <= U_opt: R_borrow = R_0 + (U / U_opt) * R_1
        If U > U_opt:  R_borrow = R_0 + R_1 + ((U - U_opt) / (1 - U_opt)) * R_2
        """
        u = self.get_utilization_rate(total_cash, total_borrows)
        p = self.params

        if u <= p.optimal_utilization:
            return p.base_rate + (u / p.optimal_utilization) * p.multiplier
        else:
            excess_u = (u - p.optimal_utilization) / (1.0 - p.optimal_utilization)
            return p.base_rate + p.multiplier + excess_u * p.jump_multiplier

    def get_supply_rate(self, total_cash: float, total_borrows: float) -> float:
        r"""Calculates instantaneous annual supply/lending yield rate:

        R_supply = U * R_borrow * (1 - reserve_factor)
        """
        u = self.get_utilization_rate(total_cash, total_borrows)
        borrow_rate = self.get_borrow_rate(total_cash, total_borrows)
        return u * borrow_rate * (1.0 - self.params.reserve_factor)
