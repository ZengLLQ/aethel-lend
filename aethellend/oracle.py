"""Price oracle feeding multi-asset market valuations."""

from __future__ import annotations
from typing import Dict


class PriceOracle:
    """Mock decentralized price feed for asset valuation in USD."""

    def __init__(self):
        self.prices: Dict[str, float] = {
            "USDC": 1.0,
            "WETH": 3000.0,
            "WBTC": 65000.0,
        }

    def set_price(self, asset: str, price_usd: float) -> None:
        if price_usd <= 0.0:
            raise ValueError("Asset price must be strictly positive.")
        self.prices[asset] = price_usd

    def get_price(self, asset: str) -> float:
        if asset not in self.prices:
            raise KeyError(f"Price for asset {asset} not found in oracle.")
        return self.prices[asset]
