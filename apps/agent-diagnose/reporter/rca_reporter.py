import json
from datetime import datetime

class RCAReporter:
    """
    Formats and outputs RCA reports.
    """

    def generate(self, anomaly_id, anomaly_type, root_cause, evidence, confidence):
        report = {
            "anomaly_id": anomaly_id,
            "timestamp": datetime.utcnow().isoformat(),
            "detected_anomaly": anomaly_type,
            "root_cause": root_cause,
            "evidence": evidence,
            "confidence": round(confidence, 2)
        }
        return report

    def print_report(self, report):
        print("\n===== ROOT CAUSE ANALYSIS REPORT =====")
        print(f"Anomaly ID: {report['anomaly_id']}")
        print(f"Time: {report['timestamp']}")
        print(f"Detected Anomaly: {report['detected_anomaly']}")
        print("\nRoot Cause:")
        print(f"  Component : {report['root_cause']['component']}")
        print(f"  Type      : {report['root_cause']['type']}")
        print(f"  Signal    : {report['root_cause']['signal']}")
        print("\nEvidence:")
        print("  Metrics:")
        for m in report["evidence"]["metrics"]:
            print(f"    - {m}")
        print("  Logs:")
        for l in report["evidence"]["logs"]:
            print(f"    - {l}")
        print("  Traces:")
        for t in report["evidence"]["traces"]:
            print(f"    - {t}")
        print(f"\nConfidence Score: {report['confidence']}")
        print("=====================================\n")

    def save_json(self, report, filepath):
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
