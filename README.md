# Payment Gateway Failure & Smart Retry Recovery Engine

A payment operations analytics framework that separates non-recoverable hard declines from transient bank timeouts, evaluates gateway authorization rates, and models optimal retry cooldown windows.

## Problem Context
Roughly 10%–14% of online checkout attempts fail on the first try. Retrying every failed payment immediately wastes processor transaction fees on invalid/expired cards, while waiting too long causes customers to abandon their carts.

## Files
- `payment_decline_recovery.sql`: Sequences checkout payment attempts via `ROW_NUMBER()` and `LEAD()`, categorizes ISO/gateway decline codes into `HARD_DECLINE` vs `SOFT_DECLINE`, and tracks retry recovery rates.
- `retry_window_optimizer.py`: Evaluates 45k+ payment transactions across processors (`Stripe`, `Adyen`, `Braintree`) and measures soft-decline recovery rates across time buckets (`0-30s`, `31s-3m`, `3m-15m`, `15m+`).
- `requirements.txt`: Python dependencies.

## Analytical Logic
1. **Hard vs. Soft Decline Separation:** Filters out permanent failures (`INSUFFICIENT_FUNDS`, `EXPIRED_CARD`, `INVALID_CVV`) from transient infrastructure errors (`ISSUER_TIMEOUT`, `GATEWAY_504`, `NETWORK_DROP`).
2. **Session-Level Retry Tracking:** Uses windowed `LEAD()` over `checkout_session_id` to link an initial failed attempt with its subsequent retry outcome and elapsed seconds.
3. **Cooldown Window Optimization:** Demonstrates that immediate retries (`<30s`) hit the same overloaded bank node, whereas a `30s–3m` cooldown window with secondary gateway routing maximizes recovery.

## How to Run

```text
git clone https://github.com/puneetgoswami1/payment-failure-recovery-analytics.git
cd payment-failure-recovery-analytics

pip install -r requirements.txt
python retry_window_optimizer.py