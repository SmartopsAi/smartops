# Metric normalization map
# Maps Prometheus metric names to AI semantic signals

METRIC_MAP = {
    "erp_simulator_memory_leak_bytes_total": "memory_leak_bytes",
    "erp_simulator_cpu_burn_ms_sum": "cpu_burn_ms",
    "erp_simulator_latency_jitter_ms_sum": "latency_jitter_ms",
    "erp_simulator_requests_total": "request_count",
    "erp_simulator_errors_total": "error_count",
    "erp_simulator_modes_enabled": "modes_enabled"
}
