"""Tests for the kinked interest rate model."""

import pytest
from aethellend.rate_model import KinkedInterestRateModel, RateParameters


def test_utilization_rate_edge_cases():
    model = KinkedInterestRateModel()
    assert model.get_utilization_rate(0.0, 0.0) == 0.0
    assert model.get_utilization_rate(100.0, 0.0) == 0.0
    assert model.get_utilization_rate(0.0, 100.0) == 1.0
    assert model.get_utilization_rate(50.0, 50.0) == 0.50


def test_borrow_rate_below_and_above_kink():
    params = RateParameters(
        base_rate=0.02,
        multiplier=0.08,
        jump_multiplier=1.00,
        optimal_utilization=0.80,
    )
    model = KinkedInterestRateModel(params)

    # At U = 0, R_borrow = 2%
    assert pytest.approx(model.get_borrow_rate(1000.0, 0.0)) == 0.02

    # At U = 0.40 (halfway to kink), R_borrow = 2% + (0.4/0.8)*8% = 6%
    assert pytest.approx(model.get_borrow_rate(600.0, 400.0)) == 0.06

    # At U = 0.80 (exact kink), R_borrow = 2% + 8% = 10%
    assert pytest.approx(model.get_borrow_rate(200.0, 800.0)) == 0.10

    # At U = 0.90 (above kink), excess = (0.9 - 0.8) / (1 - 0.8) = 0.5
    # R_borrow = 2% + 8% + 0.5 * 100% = 60%
    assert pytest.approx(model.get_borrow_rate(100.0, 900.0)) == 0.60


def test_supply_rate_with_reserve_factor():
    params = RateParameters(
        base_rate=0.02,
        multiplier=0.08,
        jump_multiplier=1.00,
        optimal_utilization=0.80,
        reserve_factor=0.20,  # 20% protocol reserve cut
    )
    model = KinkedInterestRateModel(params)

    # At U = 0.80, R_borrow = 10%.
    # R_supply = U * R_borrow * (1 - 0.20) = 0.80 * 0.10 * 0.80 = 0.064 (6.4%)
    r_supply = model.get_supply_rate(200.0, 800.0)
    assert pytest.approx(r_supply) == 0.064
