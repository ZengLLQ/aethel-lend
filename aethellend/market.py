"""Lending market engine managing multi-asset collateral, borrowing, and liquidations."""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple
from .oracle import PriceOracle
from .reserve import AssetReserve, ReserveConfig


@dataclass
class UserAccount:
    """Represents a user's multi-asset position within the money market."""
    address: str
    scaled_supplies: Dict[str, float] = field(default_factory=dict)
    scaled_borrows: Dict[str, float] = field(default_factory=dict)
    collateral_flags: Dict[str, bool] = field(default_factory=dict)

    def get_supply_balance(self, asset: str, supply_index: float) -> float:
        return self.scaled_supplies.get(asset, 0.0) * supply_index

    def get_borrow_balance(self, asset: str, borrow_index: float) -> float:
        return self.scaled_borrows.get(asset, 0.0) * borrow_index


@dataclass
class LiquidationResult:
    """Outcome of a successful liquidation auction call."""
    borrower: str
    liquidator: str
    debt_asset: str
    debt_repaid: float
    collateral_asset: str
    collateral_seized: float
    bonus_collateral: float
    new_health_factor: float


class LendingMarket:
    """Core money market controller executing state transitions and enforcing safety invariants."""

    CLOSE_FACTOR: float = 0.50  # Up to 50% of outstanding debt can be liquidated at once
    MIN_LIQUIDATION_DEBT_THRESHOLD_USD: float = 100.0  # Allow 100% liquidation for micro debts
    FLASH_LOAN_FEE_RATE: float = 0.0009  # 9 basis points (0.09%)

    def __init__(self, oracle: Optional[PriceOracle] = None, initial_timestamp: float = 0.0):
        self.oracle = oracle or PriceOracle()
        self.reserves: Dict[str, AssetReserve] = {}
        self.users: Dict[str, UserAccount] = {}
        self.current_timestamp: float = initial_timestamp

    def add_reserve(self, config: ReserveConfig) -> AssetReserve:
        """Initializes a new asset reserve pool."""
        if config.asset in self.reserves:
            raise ValueError(f"Reserve for {config.asset} already exists.")
        reserve = AssetReserve(
            asset=config.asset,
            config=config,
            initial_timestamp=self.current_timestamp,
        )
        self.reserves[config.asset] = reserve
        return reserve

    def get_reserve(self, asset: str) -> AssetReserve:
        if asset not in self.reserves:
            raise KeyError(f"Reserve {asset} is not listed in the market.")
        return self.reserves[asset]

    def get_user(self, address: str) -> UserAccount:
        if address not in self.users:
            self.users[address] = UserAccount(address=address)
        return self.users[address]

    def advance_time(self, delta_seconds: float) -> None:
        """Advances protocol clock and accrues interest across all active reserves."""
        if delta_seconds < 0:
            raise ValueError("Time delta cannot be negative.")
        self.current_timestamp += delta_seconds
        for reserve in self.reserves.values():
            reserve.accrue_interest(self.current_timestamp)

    def deposit(self, user_address: str, asset: str, amount: float) -> float:
        """Supplies liquidity into the reserve, earning variable yield."""
        if amount <= 0.0:
            raise ValueError("Deposit amount must be strictly positive.")
        reserve = self.get_reserve(asset)
        reserve.accrue_interest(self.current_timestamp)

        user = self.get_user(user_address)
        scaled_amount = amount / reserve.supply_index

        user.scaled_supplies[asset] = user.scaled_supplies.get(asset, 0.0) + scaled_amount
        if asset not in user.collateral_flags:
            user.collateral_flags[asset] = True

        reserve.total_cash += amount
        return user.get_supply_balance(asset, reserve.supply_index)

    def withdraw(self, user_address: str, asset: str, amount: float) -> float:
        """Withdraws supplied liquidity, validating that remaining collateral satisfies HF >= 1.0."""
        if amount <= 0.0:
            raise ValueError("Withdraw amount must be strictly positive.")
        reserve = self.get_reserve(asset)
        reserve.accrue_interest(self.current_timestamp)

        user = self.get_user(user_address)
        current_balance = user.get_supply_balance(asset, reserve.supply_index)
        if current_balance < amount - 1e-9:
            raise ValueError(f"Insufficient deposit balance. Requested: {amount}, available: {current_balance}")

        if reserve.total_cash < amount:
            raise ValueError(f"Reserve pool liquidity shortfall. Available cash: {reserve.total_cash}")

        # Simulate withdrawal and check safety invariant
        scaled_amount = amount / reserve.supply_index
        user.scaled_supplies[asset] -= scaled_amount
        reserve.total_cash -= amount

        total_collateral_usd, total_debt_usd, health_factor = self.get_account_liquidity(user_address)
        if total_debt_usd > 0.0 and health_factor < 1.0:
            # Revert state change
            user.scaled_supplies[asset] += scaled_amount
            reserve.total_cash += amount
            raise ValueError(f"Withdrawal violates minimum collateral health factor. HF would be {health_factor:.3f}")

        return user.get_supply_balance(asset, reserve.supply_index)

    def borrow(self, user_address: str, asset: str, amount: float) -> float:
        """Borrows assets against enabled collateral up to maximum LTV."""
        if amount <= 0.0:
            raise ValueError("Borrow amount must be strictly positive.")
        reserve = self.get_reserve(asset)
        reserve.accrue_interest(self.current_timestamp)

        if reserve.total_cash < amount:
            raise ValueError(f"Insufficient cash in reserve {asset} to borrow {amount}.")

        user = self.get_user(user_address)
        borrow_value_usd = amount * self.oracle.get_price(asset)

        # Check borrow capacity
        max_borrow_usd, current_debt_usd = self._get_borrow_capacity(user_address)
        if current_debt_usd + borrow_value_usd > max_borrow_usd + 1e-6:
            raise ValueError(
                f"Borrow exceeds available collateral capacity. "
                f"Max capacity: ${max_borrow_usd:.2f}, New debt: ${current_debt_usd + borrow_value_usd:.2f}"
            )

        scaled_borrow = amount / reserve.borrow_index
        user.scaled_borrows[asset] = user.scaled_borrows.get(asset, 0.0) + scaled_borrow

        reserve.total_cash -= amount
        reserve.total_borrows += amount

        return user.get_borrow_balance(asset, reserve.borrow_index)

    def repay(self, user_address: str, asset: str, amount: float) -> float:
        """Repays borrowed debt, returning actual amount repaid."""
        if amount <= 0.0:
            raise ValueError("Repay amount must be strictly positive.")
        reserve = self.get_reserve(asset)
        reserve.accrue_interest(self.current_timestamp)

        user = self.get_user(user_address)
        current_debt = user.get_borrow_balance(asset, reserve.borrow_index)
        if current_debt <= 0.0:
            return 0.0

        actual_repay = min(amount, current_debt)
        scaled_repay = actual_repay / reserve.borrow_index

        user.scaled_borrows[asset] -= scaled_repay
        if abs(user.scaled_borrows[asset]) < 1e-12:
            user.scaled_borrows[asset] = 0.0

        reserve.total_borrows = max(0.0, reserve.total_borrows - actual_repay)
        reserve.total_cash += actual_repay

        return actual_repay

    def set_user_use_reserve_as_collateral(self, user_address: str, asset: str, enabled: bool) -> None:
        """Toggles whether an asset deposit counts toward collateral capacity."""
        user = self.get_user(user_address)
        prev_state = user.collateral_flags.get(asset, True)
        user.collateral_flags[asset] = enabled

        if not enabled:
            _, debt_usd, hf = self.get_account_liquidity(user_address)
            if debt_usd > 0.0 and hf < 1.0:
                user.collateral_flags[asset] = prev_state
                raise ValueError("Disabling collateral drops account health factor below 1.0.")

    def get_account_liquidity(self, user_address: str) -> Tuple[float, float, float]:
        """Calculates (total_collateral_usd, total_debt_usd, health_factor)."""
        user = self.get_user(user_address)
        total_collateral_usd = 0.0
        total_liquidation_capacity_usd = 0.0
        total_debt_usd = 0.0

        for asset, reserve in self.reserves.items():
            reserve.accrue_interest(self.current_timestamp)
            price = self.oracle.get_price(asset)

            # Collateral
            if user.collateral_flags.get(asset, False):
                balance = user.get_supply_balance(asset, reserve.supply_index)
                val_usd = balance * price
                total_collateral_usd += val_usd
                total_liquidation_capacity_usd += val_usd * reserve.config.liquidation_threshold

            # Debt
            debt = user.get_borrow_balance(asset, reserve.borrow_index)
            if debt > 0.0:
                total_debt_usd += debt * price

        if total_debt_usd <= 1e-9:
            health_factor = float("inf")
        else:
            health_factor = total_liquidation_capacity_usd / total_debt_usd

        return total_collateral_usd, total_debt_usd, health_factor

    def _get_borrow_capacity(self, user_address: str) -> Tuple[float, float]:
        """Returns (max_borrow_usd, current_debt_usd)."""
        user = self.get_user(user_address)
        max_borrow_usd = 0.0
        current_debt_usd = 0.0

        for asset, reserve in self.reserves.items():
            reserve.accrue_interest(self.current_timestamp)
            price = self.oracle.get_price(asset)

            if user.collateral_flags.get(asset, False):
                balance = user.get_supply_balance(asset, reserve.supply_index)
                max_borrow_usd += balance * price * reserve.config.loan_to_value

            debt = user.get_borrow_balance(asset, reserve.borrow_index)
            current_debt_usd += debt * price

        return max_borrow_usd, current_debt_usd

    def liquidate(
        self,
        liquidator: str,
        borrower: str,
        debt_asset: str,
        debt_to_cover: float,
        collateral_asset: str,
    ) -> LiquidationResult:
        """Executes a liquidation auction when borrower's health factor drops below 1.0."""
        if debt_to_cover <= 0.0:
            raise ValueError("Debt to cover must be strictly positive.")

        debt_reserve = self.get_reserve(debt_asset)
        collateral_reserve = self.get_reserve(collateral_asset)

        debt_reserve.accrue_interest(self.current_timestamp)
        collateral_reserve.accrue_interest(self.current_timestamp)

        _, total_debt_usd, hf = self.get_account_liquidity(borrower)
        if hf >= 1.0:
            raise ValueError(f"Account is healthy (HF = {hf:.3f} >= 1.0); cannot be liquidated.")

        borrower_account = self.get_user(borrower)
        liquidator_account = self.get_user(liquidator)

        borrower_debt = borrower_account.get_borrow_balance(debt_asset, debt_reserve.borrow_index)
        if borrower_debt <= 0.0:
            raise ValueError(f"Borrower has no outstanding debt in {debt_asset}.")

        debt_price = self.oracle.get_price(debt_asset)
        collateral_price = self.oracle.get_price(collateral_asset)

        # Close factor enforcement
        total_borrower_debt_usd = borrower_debt * debt_price
        if total_borrower_debt_usd < self.MIN_LIQUIDATION_DEBT_THRESHOLD_USD:
            max_repayable = borrower_debt
        else:
            max_repayable = borrower_debt * self.CLOSE_FACTOR

        debt_repaid = min(debt_to_cover, max_repayable)
        repaid_usd = debt_repaid * debt_price

        # Collateral calculation with liquidation bonus
        bonus = collateral_reserve.config.liquidation_bonus
        collateral_usd_to_seize = repaid_usd * (1.0 + bonus)
        collateral_seized = collateral_usd_to_seize / collateral_price

        borrower_collateral = borrower_account.get_supply_balance(collateral_asset, collateral_reserve.supply_index)
        if collateral_seized > borrower_collateral:
            # Cap seized amount to available collateral and prorate repaid debt
            collateral_seized = borrower_collateral
            collateral_usd_seized = collateral_seized * collateral_price
            repaid_usd = collateral_usd_seized / (1.0 + bonus)
            debt_repaid = repaid_usd / debt_price

        bonus_amount = collateral_seized * (bonus / (1.0 + bonus))

        # Settle state
        # 1. Deduct borrower's debt
        scaled_repay = debt_repaid / debt_reserve.borrow_index
        borrower_account.scaled_borrows[debt_asset] -= scaled_repay
        debt_reserve.total_borrows = max(0.0, debt_reserve.total_borrows - debt_repaid)
        debt_reserve.total_cash += debt_repaid

        # 2. Transfer collateral from borrower to liquidator
        scaled_collateral = collateral_seized / collateral_reserve.supply_index
        borrower_account.scaled_supplies[collateral_asset] -= scaled_collateral
        liquidator_account.scaled_supplies[collateral_asset] = (
            liquidator_account.scaled_supplies.get(collateral_asset, 0.0) + scaled_collateral
        )

        _, _, new_hf = self.get_account_liquidity(borrower)

        return LiquidationResult(
            borrower=borrower,
            liquidator=liquidator,
            debt_asset=debt_asset,
            debt_repaid=debt_repaid,
            collateral_asset=collateral_asset,
            collateral_seized=collateral_seized,
            bonus_collateral=bonus_amount,
            new_health_factor=new_hf,
        )

    def flash_loan(
        self,
        receiver_fn: Callable[[str, float, float, Dict], bool],
        asset: str,
        amount: float,
        params: Optional[Dict] = None,
    ) -> float:
        """Executes uncollateralized flash loan requiring atomic single-transaction repayment."""
        if amount <= 0.0:
            raise ValueError("Flash loan amount must be positive.")
        reserve = self.get_reserve(asset)
        reserve.accrue_interest(self.current_timestamp)

        if reserve.total_cash < amount:
            raise ValueError(f"Flash loan requested {amount} exceeds available reserve cash {reserve.total_cash}.")

        fee = amount * self.FLASH_LOAN_FEE_RATE
        reserve.total_cash -= amount

        # Execute receiver callback
        success = receiver_fn(asset, amount, fee, params or {})
        if not success:
            reserve.total_cash += amount
            raise RuntimeError("Flash loan callback returned unsuccessful execution.")

        # In a simulated atomic environment, fee and principal are returned
        reserve.total_cash += amount + fee
        protocol_cut = fee * reserve.config.reserve_factor
        reserve.total_reserves += protocol_cut

        return fee
