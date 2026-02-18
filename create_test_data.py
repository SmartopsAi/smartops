import json
import os
import time

# Ensure directories exist
os.makedirs("data/runtime", exist_ok=True)
os.makedirs("policy_engine/audit", exist_ok=True)

print("Created directories: data/runtime/ and policy_engine/audit/")

# 1. Latest Detection (For Anomalies Page)
detection_data = {
    "timestamp": time.time(),
    "service": "erp-simulator",
    "anomaly_score": 0.85,
    "type": "cpu_spike",
    "model_version": "isolation_forest_v1",
    "window_id": "w-1024"
}
with open("data/runtime/latest_detection.json", "w") as f:
    json.dump(detection_data, f)
print("- Created latest_detection.json")

# 2. Latest Features (For Anomalies Page Detail)
features_data = {
    "timestamp": time.time(),
    "window_id": "w-1024",
    "features": [
        {"name": "cpu_usage", "delta": 0.45, "value": 0.95},
        {"name": "memory_usage", "delta": 0.12, "value": 0.60},
        {"name": "request_latency", "delta": 0.05, "value": 0.12}
    ]
}
with open("data/runtime/latest_features.json", "w") as f:
    json.dump(features_data, f)
print("- Created latest_features.json")

# 3. Latest RCA (For RCA Page)
rca_data = {
    "timestamp": time.time(),
    "incident_id": "inc-5501",
    "root_causes": [
        {"component": "db-shard-01", "cause": "connection_pool_exhaustion", "confidence": 0.92},
        {"component": "erp-service", "cause": "memory_leak", "confidence": 0.45}
    ],
    "evidence": {
        "trace_ids": ["a1b2c3d4", "e5f6g7h8"],
        "logs": ["Connection refused", "Timeout waiting for pool"]
    }
}
with open("data/runtime/latest_rca.json", "w") as f:
    json.dump(rca_data, f)
print("- Created latest_rca.json")

# 4. Policy Audit Log (For Policies Page & Overview)
with open("policy_engine/audit/policy_decisions.jsonl", "w") as f:
    # Write a few lines of JSONL
    f.write(json.dumps({
        "timestamp": time.time(), 
        "policy_id": "scaling_limit", 
        "decision": "block", 
        "reason": "Max replicas exceeded", 
        "guardrails_checked": [{"name": "max_replicas", "triggered": True}],
        "recommendations": ["Request approval"]
    }) + "\n")
    
    f.write(json.dumps({
        "timestamp": time.time() - 60, 
        "policy_id": "restart_safety", 
        "decision": "allow", 
        "reason": "Safe in dev environment", 
        "guardrails_checked": [{"name": "prod_freeze", "triggered": False}],
        "recommendations": []
    }) + "\n")
print("- Created policy_decisions.jsonl")

print("\nSUCCESS: Test data generated. You can now refresh the dashboard.")