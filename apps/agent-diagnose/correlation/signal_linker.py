class SignalLinker:
    """
    Links correlated signals to possible failure categories.
    """

    def infer_failure_type(self, correlated):
        if any("cpu" in m for m in correlated["metrics"]):
            return "Resource Saturation"

        if any("timeout" in l.lower() for l in correlated["logs"]):
            return "Service Timeout"

        if any("latency" in t.lower() for t in correlated["traces"]):
            return "Dependency Latency"

        return "Unknown Failure"
