# Time Windowing Strategy – SmartOps AI

## Sampling Interval

- Metrics are sampled every 5 seconds.

## Window Sizes

- Short window: 60 seconds (real-time detection)
- Long window: 300 seconds (trend analysis)

## Rationale

- Short windows enable fast detection.
- Long windows capture gradual anomalies (e.g., memory leaks).
- Balances detection latency and noise sensitivity.
