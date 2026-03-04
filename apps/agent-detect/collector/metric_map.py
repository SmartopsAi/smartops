# Metric normalization maps
# Maps Prometheus metrics / PromQL queries to AI semantic signals

# ================================
# Simulator profile (existing)
# ================================
SIMULATOR_PROFILE_METRICS = {
    "erp_simulator_memory_leak_bytes_total": "memory_leak_bytes",
    "erp_simulator_cpu_burn_ms_sum": "cpu_burn_ms",
    "erp_simulator_latency_jitter_ms_sum": "latency_jitter_ms",
    "erp_simulator_requests_total": "request_count",
    "erp_simulator_errors_total": "error_count",
    "erp_simulator_modes_enabled": "modes_enabled",
}

# ================================
# Odoo ERP profile (ingress-based)
# ================================
# NOTE:
# In your current ingress-nginx metrics endpoint, the usual per-request metrics
# (nginx_ingress_controller_requests / request_duration_seconds_bucket) are NOT exposed.
# But the controller DOES expose a strong production signal:
#   nginx_ingress_controller_orphan_ingress{ingress="odoo-ingress", namespace="smartops-dev", type="no-endpoint"} == 1
# This reliably indicates "Ingress has no endpoints" (service down / selector mismatch / scaled to 0).
ODOO_PROFILE_METRICS = {
    # ----------------------------
    # Primary production signal
    # ----------------------------
    "odoo_no_endpoint": {
        "type": "promql",
        "query": """
        max(
          nginx_ingress_controller_orphan_ingress{
            ingress="odoo-ingress",
            exported_namespace="smartops-dev",
            type="no-endpoint"
          }
        )
        """,
    },

    # ----------------------------
    # Optional future metrics
    # (Enable once request/latency metrics exist in Prometheus)
    # ----------------------------
    # "erp_req_rate": {
    #     "type": "promql",
    #     "query": """
    #     sum(
    #       rate(
    #         nginx_ingress_controller_requests{
    #           host="odoo.localhost",
    #           exported_namespace="smartops-dev"
    #         }[1m]
    #       )
    #     )
    #     """,
    # },
    #
    # "erp_5xx_rate": {
    #     "type": "promql",
    #     "query": """
    #     sum(
    #       rate(
    #         nginx_ingress_controller_requests{
    #           host="odoo.localhost",
    #           exported_namespace="smartops-dev",
    #           status=~"5.."
    #         }[1m]
    #       )
    #     )
    #     """,
    # },
    #
    # "erp_p95_latency": {
    #     "type": "promql",
    #     "query": """
    #     histogram_quantile(
    #       0.95,
    #       sum by (le) (
    #         rate(
    #           nginx_ingress_controller_request_duration_seconds_bucket{
    #             host="odoo.localhost",
    #             exported_namespace="smartops-dev"
    #           }[2m]
    #         )
    #       )
    #     )
    #     """,
    # },
}

# ================================
# Backward compatibility alias
# ================================
METRIC_MAP = SIMULATOR_PROFILE_METRICS