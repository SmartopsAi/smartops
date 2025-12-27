class TraceCollector:
    """
    Collects trace spans during anomaly windows.
    """

    def __init__(self):
        self.spans = []

    def ingest(self, trace_id, span_id, service, parent_span, duration_ms):
        self.spans.append({
            "trace_id": trace_id,
            "span_id": span_id,
            "service": service,
            "parent": parent_span,
            "duration_ms": duration_ms
        })

    def fetch_by_trace(self, trace_id):
        return [s for s in self.spans if s["trace_id"] == trace_id]
