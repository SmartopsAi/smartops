import numpy as np

def extract_metric_series(window_values, metric_name):
    """
    Extract a time-series list for a single metric from window data
    """
    return [
        entry.get(metric_name, 0.0)
        for entry in window_values
        if metric_name in entry
    ]

def compute_features(series):
    """
    Compute statistical & temporal features from a numeric series
    """
    if len(series) < 2:
        return None

    arr = np.array(series)

    mean = float(np.mean(arr))
    std = float(np.std(arr))
    minimum = float(np.min(arr))
    maximum = float(np.max(arr))

    # Trend (simple slope)
    slope = float(arr[-1] - arr[0])

    # Spike detection (max deviation from mean)
    spike = float(np.max(np.abs(arr - mean)))

    return {
        "mean": mean,
        "std": std,
        "min": minimum,
        "max": maximum,
        "slope": slope,
        "spike": spike
    }

def build_feature_vector(window_values, metrics):
    """
    Build full feature vector for selected metrics
    """
    feature_vector = {}

    for metric in metrics:
        series = extract_metric_series(window_values, metric)
        features = compute_features(series)

        if features:
            for key, value in features.items():
                feature_vector[f"{metric}_{key}"] = value

    return feature_vector
