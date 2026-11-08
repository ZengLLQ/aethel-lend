"""Example: Simulating sharp collateral price drop and liquidator execution."""

from aethellend.oracle import PriceOracle
from aethellend.reserve import ReserveConfig
from aethellend.market import LendingMarket


def run_liquidation_simulation():
    oracle = PriceOracle()
    oracle.set_price("USDC", 1.0)
    oracle.set_price("WBTC", 60000.0)

    market = LendingMarket(oracle=oracle)
    market.add_reserve(ReserveConfig(
        asset="USDC",
        loan_to_value=0.85,
        liquidation_threshold=0.90,
        liquidation_bonus=0.03,
    ))
    market.add_reserve(ReserveConfig(
        asset="WBTC",
        loan_to_value=0.70,
        liquidation_threshold=0.75,
        liquidation_bonus=0.08,  # 8% bonus for volatile asset
    ))

    # Pool liquidity
    market.deposit("lender", "USDC", 1_000_000.0)

    # Bob deposits 1 WBTC ($60,000 USD) and borrows $40,000 USDC
    print("1. Bob deposits 1.0 WBTC ($60,000) and borrows 40,000 USDC...")
    market.deposit("bob", "WBTC", 1.0)
    market.borrow("bob", "USDC", 40000.0)

    _, _, hf_init = market.get_account_liquidity("bob")
    print(f"   Initial Health Factor: {hf_init:.4f}")

    # Market crash: WBTC drops by 30% from $60,000 to $42,000
    print("\n2. Flash Crash: WBTC drops to $42,000 (-30%)...")
    oracle.set_price("WBTC", 42000.0)

    collat, debt, hf_crash = market.get_account_liquidity("bob")
    print(f"   Bob Collateral Value: ${collat:,.2f}")
    print(f"   Bob Debt Value:       ${debt:,.2f}")
    print(f"   Bob Health Factor:    {hf_crash:.4f} (Underwater!)")

    # Liquidator (Charlie) steps in
    print("\n3. Charlie liquidates 50% close factor ($20,000 USDC)...")
    res = market.liquidate(
        liquidator="charlie",
        borrower="bob",
        debt_asset="USDC",
        debt_to_cover=20000.0,
        collateral_asset="WBTC",
    )

    print(f"   Repaid Debt:        ${res.debt_repaid:,.2f} USDC")
    print(f"   WBTC Collateral Seized: {res.collateral_seized:.5f} WBTC (${res.collateral_seized * 42000:,.2f})")
    print(f"   Charlie's Profit:       {res.bonus_collateral:.5f} WBTC (${res.bonus_collateral * 42000:,.2f})")
    print(f"   Bob's New Health Factor: {res.new_health_factor:.4f}")


if __name__ == "__main__":
    run_liquidation_simulation()
