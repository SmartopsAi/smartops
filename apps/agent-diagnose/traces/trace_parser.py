class TraceParser:
    """
    Normalizes trace spans for RCA usage.
    """

    def parse(self, span):
        return {
            "service": span["service"],
            "duration_ms": span["duration_ms"],
            "parent": span["parent"]
        }
