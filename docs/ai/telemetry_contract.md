# Telemetry Contract – SmartOps AI

This document defines the semantic telemetry signals consumed by the AI layer.
The AI models do not depend on system-specific Prometheus metric names.

## Telemetry Signals

| AI Signal Name    | Source Metric (ERP Simulator)         | Description                    |
| ----------------- | ------------------------------------- | ------------------------------ |
| memory_leak_bytes | erp_simulator_memory_leak_bytes_total | Memory growth due to leaks     |
| cpu_burn_ms       | erp_simulator_cpu_burn_ms_sum         | CPU stress duration            |
| latency_jitter_ms | erp_simulator_latency_jitter_ms_sum   | Injected latency jitter        |
| request_count     | erp_simulator_requests_total          | Incoming request volume        |
| error_count       | erp_simulator_errors_total            | Error bursts                   |
| modes_enabled     | erp_simulator_modes_enabled           | Ground truth anomaly indicator |

## Notes

- These signals are streamed continuously.
- The AI layer is decoupled from raw Prometheus metric names.
- This contract allows portability to any Prometheus-based system.
