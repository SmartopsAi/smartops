import re

METRIC_LINE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{.*?\})?\s+([-+]?[0-9]*\.?[0-9eE+-]+)$'
)

def parse_prometheus_text(text: str) -> dict:
    """
    Parse Prometheus exposition format into {metric_name: value}
    """
    metrics = {}

    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue

        match = METRIC_LINE.match(line)
        if not match:
            continue

        name, value = match.groups()
        metrics[name] = float(value)

    return metrics
