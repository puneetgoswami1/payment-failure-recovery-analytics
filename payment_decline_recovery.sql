-- Payment authorization funnel, decline categorization, and retry recovery tracking
-- Evaluates checkout payment attempts across gateways and issuing banks

WITH attempt_sequences AS (
    SELECT 
        attempt_id,
        checkout_session_id,
        user_id,
        gateway_name,       -- 'Stripe', 'Adyen', 'Braintree'
        payment_method,     -- 'CREDIT_CARD', 'DEBIT_CARD', 'DIGITAL_WALLET'
        issuing_bank,
        amount_usd,
        status,             -- 'APPROVED', 'DECLINED'
        decline_code,
        attempted_at,
        
        ROW_NUMBER() OVER (
            PARTITION BY checkout_session_id 
            ORDER BY attempted_at ASC
        ) AS attempt_number,
        
        -- Check the outcome and timing of the immediate next retry in the same session
        LEAD(status, 1) OVER (
            PARTITION BY checkout_session_id 
            ORDER BY attempted_at ASC
        ) AS next_attempt_status,

        LEAD(gateway_name, 1) OVER (
            PARTITION BY checkout_session_id 
            ORDER BY attempted_at ASC
        ) AS next_attempt_gateway,

        DATEDIFF('second', attempted_at, LEAD(attempted_at, 1) OVER (
            PARTITION BY checkout_session_id 
            ORDER BY attempted_at ASC
        )) AS seconds_to_next_retry
    FROM payments_dw.fct_payment_attempts
    WHERE attempted_at >= CURRENT_DATE - INTERVAL '30 DAYS'
),

classified_failures AS (
    SELECT 
        *,
        CASE 
            WHEN status = 'APPROVED' THEN 'APPROVED'
            WHEN decline_code IN ('INSUFFICIENT_FUNDS', 'EXPIRED_CARD', 'INVALID_CVV', 'STOLEN_CARD', 'DO_NOT_HONOR') THEN 'HARD_DECLINE'
            WHEN decline_code IN ('ISSUER_TIMEOUT', 'GATEWAY_504', 'NETWORK_DROP', 'PROCESSOR_UNAVAILABLE') THEN 'SOFT_DECLINE'
            ELSE 'OTHER_DECLINE'
        END AS decline_category,

        CASE 
            WHEN status = 'DECLINED' AND next_attempt_status = 'APPROVED' THEN 1 
            ELSE 0 
        END AS was_recovered_on_retry
    FROM attempt_sequences
    WHERE attempt_number = 1 -- Evaluate initial checkout attempt performance
)

SELECT 
    gateway_name,
    decline_category,
    decline_code,
    COUNT(attempt_id) AS initial_attempts,
    ROUND(SUM(amount_usd), 2) AS gross_attempted_volume_usd,
    SUM(CASE WHEN status = 'DECLINED' THEN 1 ELSE 0 END) AS failed_count,
    SUM(was_recovered_on_retry) AS recovered_count,
    ROUND(
        (SUM(was_recovered_on_retry) * 100.0) / 
        NULLIF(SUM(CASE WHEN status = 'DECLINED' THEN 1 ELSE 0 END), 0), 2
    ) AS retry_recovery_rate_pct,
    ROUND(AVG(CASE WHEN was_recovered_on_retry = 1 THEN seconds_to_next_retry END), 0) AS avg_recovery_delay_sec
FROM classified_failures
WHERE status = 'DECLINED'
GROUP BY gateway_name, decline_category, decline_code
ORDER BY failed_count DESC;