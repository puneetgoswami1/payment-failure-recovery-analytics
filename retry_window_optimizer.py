"""
Payment Gateway Failure & Smart Retry Recovery Engine
Audits initial authorization rates, separates hard vs soft bank declines,
and identifies optimal retry timing windows to maximize checkout recovery.
"""

import numpy as np
import pandas as pd


HARD_DECLINES = ["INSUFFICIENT_FUNDS", "EXPIRED_CARD", "INVALID_CVV", "DO_NOT_HONOR"]
SOFT_DECLINES = ["ISSUER_TIMEOUT", "GATEWAY_504", "NETWORK_DROP", "PROCESSOR_UNAVAILABLE"]


def simulate_payment_attempts(n_txns: int = 45000) -> pd.DataFrame:
    """Generates realistic checkout payment logs with retry attempts and recovery outcomes."""
    rng = np.random.default_rng(42)

    gateways = rng.choice(["Stripe", "Adyen", "Braintree"], size=n_txns, p=[0.45, 0.35, 0.20])
    amounts = np.round(rng.lognormal(mean=4.2, sigma=0.55, size=n_txns), 2)

    # Initial authorization probability (~88% baseline; Braintree has slightly more timeouts)
    auth_probs = np.where(gateways == "Braintree", 0.855, 0.892)
    is_approved = rng.random(n_txns) < auth_probs

    decline_codes = []
    decline_types = []
    retried = []
    retry_delay_sec = []
    recovered = []

    for approved in is_approved:
        if approved:
            decline_codes.append("NONE")
            decline_types.append("APPROVED")
            retried.append(0)
            retry_delay_sec.append(np.nan)
            recovered.append(0)
            continue

        # 58% Soft Declines (recoverable), 42% Hard Declines (non-recoverable)
        is_soft = rng.random() < 0.58
        if is_soft:
            code = rng.choice(SOFT_DECLINES, p=[0.45, 0.25, 0.20, 0.10])
            d_type = "SOFT_DECLINE"
        else:
            code = rng.choice(HARD_DECLINES, p=[0.45, 0.20, 0.20, 0.15])
            d_type = "HARD_DECLINE"

        decline_codes.append(code)
        decline_types.append(d_type)

        # ~68% of failed checkouts trigger a retry (auto-retry or user re-click)
        did_retry = 1 if rng.random() < 0.68 else 0
        retried.append(did_retry)

        if not did_retry:
            retry_delay_sec.append(np.nan)
            recovered.append(0)
            continue

        # Simulate retry delay in seconds (between 5 sec and 45 mins)
        delay = int(rng.choice([
            rng.integers(5, 30),       # Immediate retry (<30s)
            rng.integers(31, 180),     # Sweet-spot window (30s - 3m)
            rng.integers(181, 900),    # Mid window (3m - 15m)
            rng.integers(901, 2700)    # Late retry (15m - 45m)
        ], p=[0.35, 0.30, 0.20, 0.15]))
        retry_delay_sec.append(delay)

        # Recovery probability depends heavily on decline type & timing window
        if d_type == "HARD_DECLINE":
            rec_prob = 0.04  # Hard declines rarely succeed unless user switches card
        else:
            if delay <= 30:
                rec_prob = 0.28  # Too fast; bank server still overloaded
            elif delay <= 180:
                rec_prob = 0.54  # Optimal cooldown window
            elif delay <= 900:
                rec_prob = 0.36  # User still in checkout intent
            else:
                rec_prob = 0.14  # User likely abandoned cart

        recovered.append(1 if rng.random() < rec_prob else 0)

    return pd.DataFrame({
        "txn_id": [f"PAY-{300000 + i}" for i in range(n_txns)],
        "gateway": gateways,
        "amount_usd": amounts,
        "initial_approved": is_approved.astype(int),
        "decline_type": decline_types,
        "decline_code": decline_codes,
        "retried": retried,
        "retry_delay_sec": retry_delay_sec,
        "recovered": recovered
    })


def run_payment_diagnostics(df: pd.DataFrame):
    total = len(df)
    approved = df["initial_approved"].sum()
    failed_df = df[df["initial_approved"] == 0].copy()

    print("\n--- Checkout Payment Authorization & Recovery Summary ---")
    print(f"Total Initial Attempts : {total:,}")
    print(f"First-Attempt Approved : {approved:,} ({(approved / total) * 100:.2f}%)")
    print(f"Initial Declines       : {len(failed_df):,} (${failed_df['amount_usd'].sum():,.2f} at risk)\n")

    # 1. Gateway Authorization & Soft-Decline Exposure
    gw_summary = (
        df.groupby("gateway")
        .agg(
            attempts=("txn_id", "count"),
            auth_rate_pct=("initial_approved", lambda x: round(x.mean() * 100, 2)),
            soft_declines=("decline_type", lambda x: (x == "SOFT_DECLINE").sum()),
            recovered_txns=("recovered", "sum"),
            recovered_rev_usd=("amount_usd", lambda s: round(s[df.loc[s.index, "recovered"] == 1].sum(), 2))
        )
        .reset_index()
        .sort_values("auth_rate_pct")
    )
    print("Gateway Performance & Recovered Revenue:")
    print(gw_summary.to_string(index=False))

    # 2. Retry Timing Sensitivity Analysis (Soft Declines Only)
    soft_retried = failed_df[(failed_df["decline_type"] == "SOFT_DECLINE") & (failed_df["retried"] == 1)].copy()
    bins = [0, 30, 180, 900, 3600]
    labels = ["0-30s (Immediate)", "31s-3m (Cooldown)", "3m-15m (Delayed)", "15m+ (Late)"]
    soft_retried["retry_bucket"] = pd.cut(soft_retried["retry_delay_sec"], bins=bins, labels=labels)

    timing_perf = (
        soft_retried.groupby("retry_bucket", observed=False)
        .agg(
            retry_count=("txn_id", "count"),
            recovery_rate_pct=("recovered", lambda x: round(x.mean() * 100, 1)),
            recovered_usd=("amount_usd", lambda s: round(s[soft_retried.loc[s.index, "recovered"] == 1].sum(), 2))
        )
        .reset_index()
    )

    print("\nSoft-Decline Recovery Rate by Retry Window:")
    print(timing_perf.to_string(index=False))
    print("\nActionable Fix: Suppress auto-retries on HARD_DECLINE codes (saves gateway fees) and")
    print("                schedule smart fallback routing at a 45-second cooldown for SOFT_DECLINEs.\n")


if __name__ == "__main__":
    txns = simulate_payment_attempts(45000)
    run_payment_diagnostics(txns)