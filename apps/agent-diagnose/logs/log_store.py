class LogStore:
    """
    Stores structured logs for RCA correlation.
    """

    def __init__(self):
        self.events = []

    def add(self, event):
        self.events.append(event)

    def query(self, start_ts, end_ts, min_severity=None):
        results = []

        for e in self.events:
            if start_ts <= e["timestamp"] <= end_ts:
                if min_severity:
                    if e["severity"] in ["ERROR", "WARNING"]:
                        results.append(e)
                else:
                    results.append(e)

        return results
