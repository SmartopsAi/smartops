import time
from rca_engine import RCAEngine
from correlation.correlator import Correlator
from correlation.signal_linker import SignalLinker
from decision.rca_decider import RCADecider
from reporter.rca_reporter import RCAReporter

def run_rca(anomaly_type, metric_events, log_events, trace_events):
    # Stage 3.4
    correlator = Correlator()
    linker = SignalLinker()
    correlated = correlator.correlate(
        metric_events, log_events, trace_events
    )
    failure_type = linker.infer_failure_type(correlated)

    # Stage 3.5
    decider = RCADecider()
    root_cause, confidence = decider.decide(
        correlated, failure_type
    )

    # Stage 3.6
    reporter = RCAReporter()
    anomaly_id = f"A-{int(time.time())}"

    report = reporter.generate(
        anomaly_id,
        anomaly_type,
        root_cause,
        correlated,
        confidence
    )

    reporter.print_report(report)
    reporter.save_json(report, f"data/rca/{anomaly_id}.json")

if __name__ == "__main__":
    # Simulated input from Phase 2
    run_rca(
        anomaly_type="cpu_spike",
        metric_events=["cpu_burn_ms ↑", "request_count ↑"],
        log_events=[
                        {
                            "severity": "ERROR",
                            "message": "TimeoutError in OrderService"
                        }
                    ]
                    ,
        trace_events=[
            {"from": "OrderService", "to": "DatabaseService", "latency": 850}
        ]
    )
