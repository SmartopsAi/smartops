import os
import logging
from flask import Flask, render_template, jsonify
from apps.dashboard.services.artifact_reader import ArtifactReader

from apps.dashboard.services.smartops_clients import OrchestratorClient
from flask import request

from apps.dashboard.services.prometheus_client import PrometheusClient

from apps.dashboard.services.dto import FeatureSnapshot, RcaReport

prom = PrometheusClient()

orchestrator = OrchestratorClient()

# Initialize App and Logging
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard")

# Initialize Services
reader = ArtifactReader()

# Configuration (Mode Detection)
# If KUBERNETES_SERVICE_HOST is set, we are likely in K8s mode
MODE = "k8s" if os.environ.get("KUBERNETES_SERVICE_HOST") else "local"

@app.context_processor
def inject_globals():
    """Available in all templates"""
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

# --- API ROUTES (JSON Data for Charts) ---

@app.route('/api/overview')
def api_overview():
    """Aggregates data for the overview dashboard tiles"""
    # 1. Get latest detected anomaly
    anomaly = reader.get_latest_anomaly()
    
    # 2. Get latest root cause
    rca = reader.get_latest_rca()
    
    # 3. Get recent policy decisions (last 5)
    decisions = reader.get_recent_decisions(limit=5)
    
    return jsonify({
        "status": "ok",
        "mode": MODE,
        "latest_anomaly": anomaly.__dict__ if anomaly else None,
        "latest_rca": rca.__dict__ if rca else None,
        "recent_decisions": [d.__dict__ for d in decisions],
        "system_status": "Healthy" if not anomaly else "Degraded"
    })


@app.route('/api/actions/trigger', methods=['POST'])
def trigger_action():
    data = request.json
    action_type = data.get('action')
    ns = data.get('namespace', 'smartops-dev')
    name = data.get('name')
    dry_run = data.get('dry_run', True)

    if action_type == 'scale':
        replicas = data.get('replicas', 1)
        # Call Orchestrator
        result = orchestrator.trigger_scale(ns, name, replicas, dry_run)
        return jsonify(result)
        
    elif action_type == 'restart':
        # Call Orchestrator
        result = orchestrator.trigger_restart(ns, name, dry_run)
        return jsonify(result)

    return jsonify({"status": "error", "message": "Invalid action type"}), 400


@app.route('/api/services/metrics')
def api_service_metrics():
    # Fetch metrics for key services
    # 'erp-simulator' must match the label in your ServiceMonitor/Deployment
    erp_metrics = prom.get_service_metrics("erp-simulator")
    
    # We can add Orchestrator metrics here if instrumentation exists
    orch_metrics = prom.get_service_metrics("smartops-orchestrator")

    return jsonify({
        "erp": erp_metrics,
        "orchestrator": orch_metrics
    })



@app.route('/api/anomalies')
def api_anomalies():
    """Provides data for the Anomaly Detection page"""
    # 1. Get latest detection details
    anomaly = reader.get_latest_anomaly()
    
    # 2. Get feature importance (Why was it anomalous?)
    features = reader.get_latest_features()
    
    return jsonify({
        "status": "ok",
        "latest_event": anomaly.__dict__ if anomaly else None,
        "feature_breakdown": features.__dict__ if features else None
    })

@app.route('/api/rca')
def api_rca():
    """Provides data for the Root Cause Analysis page"""
    # 1. Get the full RCA report
    report = reader.get_latest_rca()
    
    return jsonify({
        "status": "ok",
        "report": report.__dict__ if report else None
    })


@app.route('/api/policies')
def api_policies():
    """Returns full history of policy decisions for the Policies page"""
    # Fetch recent decisions (e.g., last 50)
    decisions = reader.get_recent_decisions(limit=50)
    
    return jsonify({
        "status": "ok",
        "decisions": [d.__dict__ for d in decisions]
    })



if __name__ == '__main__':
    # Local development run
    app.run(host='0.0.0.0', port=5000, debug=True)


