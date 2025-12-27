import time
from collections import deque

class SlidingWindow:
    def __init__(self, window_size_seconds: int):
        self.window_size = window_size_seconds
        self.buffer = deque()

    def add(self, timestamp: float, data: dict):
        self.buffer.append((timestamp, data))
        self._cleanup(timestamp)

    def _cleanup(self, now: float):
        while self.buffer and now - self.buffer[0][0] > self.window_size:
            self.buffer.popleft()

    def values(self):
        return [item[1] for item in self.buffer]

    def is_ready(self):
        return len(self.buffer) > 1
