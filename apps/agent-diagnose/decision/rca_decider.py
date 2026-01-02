class RCADecider:
    """
    Decides final root cause based on correlated evidence.
    """

    def decide(self, correlated, failure_type):
        score = 0.0
        component = "UNKNOWN"
        signal = "Insufficient evidence"

        # -------------------------------
        # Metrics evidence (strong)
        # -------------------------------
        if correlated["metrics"]:
            score += 0.4
            signal = correlated["metrics"][0]

        # -------------------------------
        # Log evidence (medium)
        # -------------------------------
        if correlated["logs"]:
            score += 0.3
            if "OrderService" in correlated["logs"][0]:
                component = "OrderService"

        # -------------------------------
        # Trace evidence (strong)
        # -------------------------------
        if correlated["traces"]:
            score += 0.4
            trace = correlated["traces"][0]
            component = trace.split("→")[-1].split("(")[0].strip()

        # -------------------------------
        # Normalize confidence
        # -------------------------------
        confidence = min(score, 1.0)

        root_cause = {
            "component": component,
            "type": failure_type,
            "signal": signal
        }

        return root_cause, confidence
