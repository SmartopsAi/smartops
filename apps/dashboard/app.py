import os
import logging
import requests
from flask import Flask, render_template, jsonify, request
from services.artifact_reader import ArtifactReader
from services.smartops_clients import OrchestratorClient
from services.prometheus_client import PrometheusClient
from services.dto import FeatureSnapshot, RcaReport

logging.basicConfig(level=logging.DEBUG)

prom = PrometheusClient()
orchestrator = OrchestratorClient()

# Initialize App and Logging
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard")

# Initialize Services
reader = ArtifactReader()

# Configuration (Mode Detection)
MODE = "k8s" if os.environ.get("KUBERNETES_SERVICE_HOST") else "local"

# -------------------------------------------------
# External Service URLs
# -------------------------------------------------
POLICY_ENGINE_URL = os.getenv(
    "POLICY_ENGINE_URL",
    "http://127.0.0.1:5051"
).rstrip("/")


@app.context_processor
def inject_globals():
    return {'mode': MODE}

# --- PAGE ROUTES (HTML) ---

@app.route('/')
def index():
    return render_template('overview.html', page="overview")

@app.route('/overview')
def page_overview():
    return render_template('overview.html', page="overview")

@app.route('/services')
def page_services():
    return render_template('services.html', page="services")

@app.route('/anomalies')
def page_anomalies():
    return render_template('anomalies.html', page="anomalies")

@app.route('/rca')
def page_rca():
    return render_template('rca.html', page="rca")

@app.route('/policies')
def page_policies():
    return render_template('policies.html', page="policies")

@app.route('/actions')
def page_actions():
    return render_template('actions.html', page="actions")

@app.route('/verification')
def page_verification():
    return render_template('verification.html', page="verification")

@app.route('/telemetry')
def page_telemetry():
    return render_template('telemetry.html', page="telemetry")

# --- API ROUTES ---

@app.route('/api/overview')
def api_overview():
    """
    Aggregates data for the overview dashboard tiles.
    Extended with ERP Pilot (Odoo) KPIs.
    """
    anomaly = reader.get_latest_anomaly()
    rca = reader.get_latest_rca()
    decisions = reader.get_recent_decisions(limit=5)

    # 🔹 NEW: ERP Pilot KPIs (Odoo)
    erp_odoo = prom.get_odoo_kpis()

    return jsonify({
        "status": "ok",
        "mode": MODE,
        "system_status": "Healthy" if not anomaly else "Degraded",
        "latest_anomaly": anomaly.__dict__ if anomaly else None,
        "latest_rca": rca.__dict__ if rca else None,
        "recent_decisions": [d.__dict__ for d in decisions],
        "erp_odoo": erp_odoo,
    })


@app.route('/api/verification', methods=['POST'])
def api_verification():
    data = request.json
    result = orchestrator.verify_deployment(
        namespace=data.get("namespace"),
        deployment=data.get("deployment"),
        expected_replicas=data.get("expected_replicas"),
    )
    return jsonify(result)


@app.route('/api/actions/trigger', methods=['POST'])
def trigger_action():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        action_type = data.get('action')
        ns = data.get('namespace', 'smartops-dev')
        name = data.get('name')
        dry_run = data.get('dry_run', True)

        if not name:
            return jsonify({"status": "error", "message": "Deployment name required"}), 400

        if action_type == 'scale':
            replicas = int(data.get('replicas', 1))
            result = orchestrator.trigger_scale(ns, name, replicas, dry_run)
        elif action_type == 'restart':
            result = orchestrator.trigger_restart(ns, name, dry_run)
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400

        return jsonify({"status": "success", "result": result})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/anomalies')
def api_anomalies():
    anomaly = reader.get_latest_anomaly()
    features = reader.get_latest_features()
    return jsonify({
        "status": "ok",
        "latest_event": anomaly.__dict__ if anomaly else None,
        "feature_breakdown": features.__dict__ if features else None
    })


@app.route('/api/rca')
def api_rca():
    report = reader.get_latest_rca()
    return jsonify({
        "status": "ok",
        "report": report.__dict__ if report else None
    })


@app.route('/api/policies')
def api_policies():
    try:
        resp = requests.get(
            f"{POLICY_ENGINE_URL}/v1/policy/audit/latest?n=50",
            timeout=3,
        )
        resp.raise_for_status()
        raw = resp.json().get("events", [])

        normalized = []
        for ev in raw:
            decision_raw = ev.get("decision")
            if decision_raw == "action":
                decision = "allow"
            elif decision_raw == "blocked":
                decision = "block"
            else:
                decision = "no_action"

            normalized.append({
                "ts": ev.get("ts_utc"),
                "decision": decision,
                "policy_id": ev.get("policy", "-"),
                "reason": ev.get("guardrail_reason") or ev.get("reason") or "-",
            })

        return jsonify({"status": "ok", "decisions": normalized})

    except Exception as exc:
        return jsonify({
            "status": "error",
            "error": str(exc),
            "decisions": []
        })


@app.route('/api/services/metrics')
def api_service_metrics():
    namespace = "smartops-dev"

    erp_health = prom.get_deployment_health(namespace, "smartops-erp-simulator")
    orch_health = prom.get_deployment_health(namespace, "smartops-orchestrator")

    erp_latency_ms = prom.get_latency_p95_ms_progressive({
        "namespace": namespace
    })

    return jsonify({
        "status": "ok",
        "mode": MODE,
        "prometheus_url": prom.base_url if prom.enabled else None,
        "erp": {**erp_health, "p95_latency_ms": erp_latency_ms},
        "orchestrator": {**orch_health, "p95_latency_ms": None},
    })


@app.route("/api/policy/decisions")
def policy_decisions():
    try:
        resp = requests.get(
            f"{POLICY_ENGINE_URL}/v1/policy/audit/latest?n=10",
            timeout=3,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "events": [],
        }, 200


port = int(os.environ.get("DASHBOARD_PORT", 5050))
app.run(host='0.0.0.0', port=port, debug=True)
