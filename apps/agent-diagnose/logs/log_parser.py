import re

class LogParser:
    """
    Normalizes raw log messages into structured events.
    """

    ERROR_PATTERNS = [
        "error", "exception", "timeout", "failed"
    ]

    WARNING_PATTERNS = [
        "warning", "slow", "retry"
    ]

    def parse(self, log):
        msg = log["message"].lower()

        severity = "INFO"
        if any(p in msg for p in self.ERROR_PATTERNS):
            severity = "ERROR"
        elif any(p in msg for p in self.WARNING_PATTERNS):
            severity = "WARNING"

        return {
            "timestamp": log["timestamp"],
            "severity": severity,
            "message": log["message"]
        }
