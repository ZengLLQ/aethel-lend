"""Comprehensive tests for LendingMarket operations, collateral, and liquidations."""

import pytest
from aethellend.oracle import PriceOracle
from aethellend.reserve import ReserveConfig, SECONDS_PER_YEAR
from aethellend.market import LendingMarket


@pytest.fixture
def populated_market():
    oracle = PriceOracle()
    oracle.set_price("USDC", 1.0)
    oracle.set_price("WETH", 2000.0)

    market = LendingMarket(oracle=oracle)
    market.add_reserve(ReserveConfig(
        asset="USDC",
        loan_to_value=0.80,
        liquidation_threshold=0.85,
        liquidation_bonus=0.05,
    ))
    market.add_reserve(ReserveConfig(
        asset="WETH",
        loan_to_value=0.70,
        liquidation_threshold=0.75,
        liquidation_bonus=0.05,
    ))
    return market


def test_deposit_and_withdraw(populated_market):
    market = populated_market

    # Alice deposits 5 WETH ($10,000 USD)
    market.deposit("alice", "WETH", 5.0)
    collat, debt, hf = market.get_account_liquidity("alice")
    assert collat == 10000.0
    assert debt == 0.0
    assert hf == float("inf")

    # Alice withdraws 2 WETH
    market.withdraw("alice", "WETH", 2.0)
    collat, debt, hf = market.get_account_liquidity("alice")
    assert collat == 6000.0


def test_borrow_within_and_exceeding_capacity(populated_market):
    market = populated_market

    # Pool funding
    market.deposit("lender", "USDC", 50000.0)

    # Alice deposits 10 WETH ($20,000 USD, LTV 70% -> max borrow capacity $14,000)
    market.deposit("alice", "WETH", 10.0)

    # Borrow $10,000 USDC -> safe
    market.borrow("alice", "USDC", 10000.0)
    _, debt, hf = market.get_account_liquidity("alice")
    assert debt == 10000.0
    # Liquidation threshold is 75% -> $15,000 LT capacity / $10,000 debt = 1.50
    assert pytest.approx(hf) == 1.50

    # Attempt to borrow $5,000 more (total $15,000 > max $14,000) -> should raise
    with pytest.raises(ValueError, match="Borrow exceeds available collateral capacity"):
        market.borrow("alice", "USDC", 5000.0)


def test_withdraw_blocked_if_drops_hf_below_one(populated_market):
    market = populated_market
    market.deposit("lender", "USDC", 50000.0)

    # Alice deposits 10 WETH ($20,000) and borrows $12,000 USDC
    market.deposit("alice", "WETH", 10.0)
    market.borrow("alice", "USDC", 12000.0)

    # Attempt to withdraw 5 WETH -> remaining 5 WETH = $10,000, LT capacity = $7,500 < $12,000 debt -> fails
    with pytest.raises(ValueError, match="Withdrawal violates minimum collateral health factor"):
        market.withdraw("alice", "WETH", 5.0)


def test_repay_and_interest_accrual(populated_market):
    market = populated_market
    market.deposit("lender", "USDC", 50000.0)

    market.deposit("alice", "WETH", 10.0)
    market.borrow("alice", "USDC", 10000.0)

    # Advance time 1 year
    market.advance_time(SECONDS_PER_YEAR)

    # Debt should have grown due to interest
    _, debt_after, _ = market.get_account_liquidity("alice")
    assert debt_after > 10000.0

    # Repay partial
    repaid = market.repay("alice", "USDC", 5000.0)
    assert repaid == 5000.0

    # Repay all remaining
    repaid_all = market.repay("alice", "USDC", 20000.0)
    assert repaid_all == pytest.approx(debt_after - 5000.0)

    _, final_debt, final_hf = market.get_account_liquidity("alice")
    assert final_debt == 0.0
    assert final_hf == float("inf")


def test_liquidation_flow(populated_market):
    market = populated_market
    oracle = market.oracle

    # Lender deposits 100k USDC
    market.deposit("lender", "USDC", 100000.0)

    # Alice deposits 5 WETH ($10,000), borrows $7,000 USDC (max 70% LTV)
    market.deposit("alice", "WETH", 5.0)
    market.borrow("alice", "USDC", 7000.0)

    # Attempt liquidation while healthy
    with pytest.raises(ValueError, match="Account is healthy"):
        market.liquidate("bob", "alice", "USDC", 3500.0, "WETH")

    # WETH price crashes from $2,000 to $1,500
    # Alice collateral = 5 * 1500 = $7,500.
    # LT capacity = $7,500 * 0.75 = $5,625.
    # Debt = $7,000.
    # Health factor = 5625 / 7000 = 0.8035 < 1.0!
    oracle.set_price("WETH", 1500.0)
    _, _, hf_under = market.get_account_liquidity("alice")
    assert hf_under < 1.0

    # Bob liquidates Alice for 50% close factor = $3,500 USDC
    # Collateral seized: $3,500 * 1.05 = $3,675 worth of WETH.
    # At $1,500/WETH, seized WETH = 3675 / 1500 = 2.45 WETH.
    res = market.liquidate("bob", "alice", debt_asset="USDC", debt_to_cover=3500.0, collateral_asset="WETH")

    assert res.debt_repaid == 3500.0
    assert pytest.approx(res.collateral_seized) == 2.45
    assert res.liquidator == "bob"
    assert res.new_health_factor > hf_under


def test_flash_loan(populated_market):
    market = populated_market
    market.deposit("lender", "USDC", 10000.0)

    called = False

    def receiver_callback(asset, amount, fee, params):
        nonlocal called
        called = True
        assert asset == "USDC"
        assert amount == 1000.0
        assert fee == pytest.approx(1000.0 * 0.0009)
        return True

    fee_paid = market.flash_loan(receiver_callback, "USDC", 1000.0)
    assert called is True
    assert pytest.approx(fee_paid) == 0.90
    assert market.get_reserve("USDC").total_cash == pytest.approx(10000.0 + 0.90)
