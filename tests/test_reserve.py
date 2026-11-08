"""Tests for reserve accrual and compounding indices."""

import pytest
from aethellend.reserve import AssetReserve, ReserveConfig, SECONDS_PER_YEAR


def test_reserve_initialization():
    config = ReserveConfig(asset="USDC", loan_to_value=0.80, liquidation_threshold=0.85)
    reserve = AssetReserve(asset="USDC", config=config, initial_timestamp=1000.0)

    assert reserve.asset == "USDC"
    assert reserve.total_cash == 0.0
    assert reserve.total_borrows == 0.0
    assert reserve.borrow_index == 1.0
    assert reserve.supply_index == 1.0
    assert reserve.last_update_timestamp == 1000.0


def test_reserve_accrue_interest():
    config = ReserveConfig(asset="USDC", reserve_factor=0.10)
    reserve = AssetReserve(asset="USDC", config=config, initial_timestamp=0.0)

    reserve.total_cash = 200.0
    reserve.total_borrows = 800.0  # U = 80%, borrow rate = 10%, supply rate = 7.2%

    # Advance exactly 1 full year
    reserve.accrue_interest(SECONDS_PER_YEAR)

    # Expected borrow interest = 800 * 0.10 = 80.0
    # Expected protocol cut = 80 * 0.10 = 8.0
    assert pytest.approx(reserve.total_borrows, rel=1e-3) == 880.0
    assert pytest.approx(reserve.total_reserves, rel=1e-3) == 8.0
    assert pytest.approx(reserve.borrow_index, rel=1e-3) == 1.10
    assert pytest.approx(reserve.supply_index, rel=1e-3) == 1.072
    assert reserve.last_update_timestamp == SECONDS_PER_YEAR


def test_reserve_accrue_zero_elapsed_time():
    reserve = AssetReserve(asset="DAI", initial_timestamp=500.0)
    reserve.total_cash = 1000.0
    reserve.total_borrows = 500.0
    initial_borrow_idx = reserve.borrow_index

    reserve.accrue_interest(500.0)
    assert reserve.borrow_index == initial_borrow_idx

    reserve.accrue_interest(400.0)  # Time backwards
    assert reserve.borrow_index == initial_borrow_idx
