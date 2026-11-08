"""Command-line interface for AethelLend money market operations and simulations."""

import click
import json
import time
from .rate_model import KinkedInterestRateModel, RateParameters
from .oracle import PriceOracle
from .reserve import ReserveConfig
from .market import LendingMarket


@click.group()
def cli():
    """AethelLend: Decentralized Money Market & Lending Protocol CLI."""
    pass


@cli.command()
@click.option("--weth-deposit", default=10.0, help="Initial WETH deposit by borrower.")
@click.option("--usdc-borrow", default=18000.0, help="USDC borrow amount by borrower.")
@click.option("--price-drop", default=0.35, help="Percentage drop in WETH collateral price.")
def simulate(weth_deposit: float, usdc_borrow: float, price_drop: float):
    """Simulates deposit, borrow, oracle shock, and liquidation auction."""
    click.echo("=" * 60)
    click.echo(">>> AethelLend Liquidation & Solvency Simulation <<<")
    click.echo("=" * 60)

    oracle = PriceOracle()
    oracle.set_price("WETH", 3000.0)
    oracle.set_price("USDC", 1.0)

    market = LendingMarket(oracle=oracle)
    market.add_reserve(ReserveConfig(asset="WETH", loan_to_value=0.75, liquidation_threshold=0.80, liquidation_bonus=0.05))
    market.add_reserve(ReserveConfig(asset="USDC", loan_to_value=0.85, liquidation_threshold=0.90, liquidation_bonus=0.03))

    # Supplier liquidity
    market.deposit("lender", "USDC", 100000.0)
    click.echo("[1] Lender deposited 100,000 USDC liquidity.")

    # Borrower deposit & borrow
    market.deposit("alice", "WETH", weth_deposit)
    weth_val = weth_deposit * 3000.0
    click.echo(f"[2] Alice deposited {weth_deposit:.2f} WETH (${weth_val:,.2f} USD).")

    market.borrow("alice", "USDC", usdc_borrow)
    click.echo(f"[3] Alice borrowed {usdc_borrow:,.2f} USDC.")

    collat, debt, hf = market.get_account_liquidity("alice")
    click.echo(f"    Alice Health Factor: {hf:.4f} (Safe)")

    # Simulate price shock
    new_price = 3000.0 * (1.0 - price_drop)
    click.echo(f"\n[4] Shocking WETH Price from $3,000 to ${new_price:.2f} (-{price_drop*100:.1f}%)...")
    oracle.set_price("WETH", new_price)

    collat, debt, hf_after = market.get_account_liquidity("alice")
    click.echo(f"    Alice Collateral Value: ${collat:,.2f}")
    click.echo(f"    Alice Debt Value:       ${debt:,.2f}")
    click.echo(f"    Alice Health Factor:    {hf_after:.4f} (Undercollateralized: {hf_after < 1.0})")

    if hf_after < 1.0:
        click.echo("\n[5] Bob (Liquidator) executing liquidation on Alice...")
        res = market.liquidate("bob", "alice", debt_asset="USDC", debt_to_cover=usdc_borrow * 0.5, collateral_asset="WETH")
        click.echo(f"    Repaid Debt:         {res.debt_repaid:,.2f} USDC")
        click.echo(f"    Collateral Seized:   {res.collateral_seized:.4f} WETH (${res.collateral_seized * new_price:,.2f})")
        click.echo(f"    Liquidator Profit:   {res.bonus_collateral:.4f} WETH (${res.bonus_collateral * new_price:,.2f})")
        click.echo(f"    Alice New Health:    {res.new_health_factor:.4f}")
    click.echo("=" * 60)


@cli.command()
@click.option("--iterations", default=5000, help="Number of simulated market operations.")
def benchmark(iterations: int):
    """Benchmarks core lending market operations throughput."""
    oracle = PriceOracle()
    market = LendingMarket(oracle=oracle)
    market.add_reserve(ReserveConfig(asset="USDC", loan_to_value=0.85, liquidation_threshold=0.90))
    market.add_reserve(ReserveConfig(asset="WETH", loan_to_value=0.75, liquidation_threshold=0.80))

    start = time.perf_counter()
    market.deposit("whale", "USDC", 10_000_000.0)

    for i in range(iterations):
        user = f"user_{i % 50}"
        market.deposit(user, "WETH", 0.1)
        market.borrow(user, "USDC", 100.0)
        market.repay(user, "USDC", 50.0)

    elapsed = time.perf_counter() - start
    ops = (iterations * 3 + 1) / elapsed
    click.echo(f"Benchmark completed: {iterations * 3 + 1} operations in {elapsed:.4f}s ({ops:,.1f} ops/sec)")


if __name__ == "__main__":
    cli()
