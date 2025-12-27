from collections import defaultdict

class DependencyGraph:
    """
    Builds service dependency graphs from traces.
    """

    def __init__(self):
        self.graph = defaultdict(list)

    def add_span(self, service, parent_service, duration_ms):
        if parent_service:
            self.graph[parent_service].append({
                "service": service,
                "latency": duration_ms
            })

    def get_hot_paths(self, latency_threshold=200):
        """
        Returns service paths with high latency.
        """
        hot = []
        for parent, children in self.graph.items():
            for c in children:
                if c["latency"] >= latency_threshold:
                    hot.append({
                        "from": parent,
                        "to": c["service"],
                        "latency": c["latency"]
                    })
        return hot
