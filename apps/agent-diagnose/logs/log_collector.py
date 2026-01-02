import time

class LogCollector:
    """
    Collects logs during anomaly windows.
    """

    def __init__(self):
        self.buffer = []

    def ingest(self, timestamp, level, message):
        self.buffer.append({
            "timestamp": timestamp,
            "level": level,
            "message": message
        })

    def fetch_between(self, start_ts, end_ts):
        return [
            log for log in self.buffer
            if start_ts <= log["timestamp"] <= end_ts
        ]
