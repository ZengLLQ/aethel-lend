"""Example: End-to-end deposit, collateral leverage, borrow, and interest accrual."""

from aethellend.oracle import PriceOracle
from aethellend.reserve import ReserveConfig, SECONDS_PER_YEAR
from aethellend.market import LendingMarket


def run_cycle():
    oracle = PriceOracle()
    oracle.set_price("USDC", 1.0)
    oracle.set_price("WETH", 2500.0)

    market = LendingMarket(oracle=oracle)
    market.add_reserve(ReserveConfig(asset="USDC", loan_to_value=0.85, liquidation_threshold=0.90))
    market.add_reserve(ReserveConfig(asset="WETH", loan_to_value=0.75, liquidation_threshold=0.80))

    # Pool bootstrap
    print("1. Liquidity Provider deposits 200,000 USDC...")
    market.deposit("lp_whale", "USDC", 200_000.0)

    # Borrower deposits collateral
    print("2. Alice deposits 4.0 WETH as collateral ($10,000 USD)...")
    market.deposit("alice", "WETH", 4.0)

    collat, debt, hf = market.get_account_liquidity("alice")
    print(f"   Alice Position -> Collateral: ${collat:,.2f}, Debt: ${debt:,.2f}, Health Factor: {hf}")

    # Borrow USDC
    borrow_amount = 6000.0
    print(f"3. Alice borrows {borrow_amount:,.2f} USDC...")
    market.borrow("alice", "USDC", borrow_amount)

    collat, debt, hf = market.get_account_liquidity("alice")
    print(f"   Alice Position -> Collateral: ${collat:,.2f}, Debt: ${debt:,.2f}, Health Factor: {hf:.4f}")

    # Accrue interest over 180 days
    days_180 = 180 * 86400
    print(f"4. Fast-forwarding time 180 days...")
    market.advance_time(days_180)

    collat, debt_accrued, hf_accrued = market.get_account_liquidity("alice")
    interest_incurred = debt_accrued - borrow_amount
    print(f"   Accrued Debt: ${debt_accrued:,.2f} (Interest: +${interest_incurred:,.2f})")
    print(f"   New Health Factor: {hf_accrued:.4f}")

    # Full repayment
    print("5. Alice repays full outstanding debt...")
    repaid = market.repay("alice", "USDC", debt_accrued + 10.0)
    print(f"   Total Repaid: ${repaid:,.2f}")

    collat, final_debt, final_hf = market.get_account_liquidity("alice")
    print(f"   Alice Position -> Final Debt: ${final_debt:.2f}, Health Factor: {final_hf}")


if __name__ == "__main__":
    run_cycle()
