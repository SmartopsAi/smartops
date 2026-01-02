class Correlator:
    """
    Correlates metrics, logs, and traces within the same anomaly window.
    """

    def correlate(self, metric_events, log_events, trace_events):
        correlated = {
            "metrics": [],
            "logs": [],
            "traces": []
        }

        # Metrics → primary signals
        for m in metric_events:
            if m.endswith("↑") or m.endswith("↓"):
                correlated["metrics"].append(m)

        # Logs → supporting evidence
        for l in log_events:
            if l["severity"] in ["ERROR", "WARNING"]:
                correlated["logs"].append(l["message"])

        # Traces → propagation paths
        for t in trace_events:
            correlated["traces"].append(
                f"{t['from']} → {t['to']} ({t['latency']}ms)"
            )

        return correlated
