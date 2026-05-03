import PageHeader from "../components/PageHeader";

const INTEGRATIONS = [
  {
    title: "Dashboard API",
    purpose: "Provides dashboard state, evidence, policy decision, and operational control endpoints.",
    method: "HTTP API consumed by Dashboard UI and external operators.",
    reference: "GET /api/dashboard/state",
    status: "Configured",
  },
  {
    title: "Orchestrator API",
    purpose: "Executes approved remediation actions against Kubernetes workloads.",
    method: "HTTP action trigger with Kubernetes RBAC-backed execution.",
    reference: "POST /api/actions/trigger",
    status: "Available",
  },
  {
    title: "Policy Engine API",
    purpose: "Evaluates DSL policies, guardrails, and priority matrix decisions.",
    method: "Policy decision service integrated into the closed-loop flow.",
    reference: "GET /api/policy/decisions",
    status: "Available",
  },
  {
    title: "Agent Detect",
    purpose: "Processes workload telemetry and emits anomaly signals.",
    method: "Prometheus metrics, logs, traces, or anomaly signal ingestion.",
    reference: "k8s/",
    status: "Repository artifact",
  },
  {
    title: "Agent Diagnose",
    purpose: "Builds RCA evidence for detected anomaly windows.",
    method: "RCA agent deployment connected to observed signals.",
    reference: "k8s/",
    status: "Repository artifact",
  },
  {
    title: "Kubernetes Manifests",
    purpose: "Deploys SmartOps services into Kubernetes namespace smartops-dev.",
    method: "kubectl apply against DigitalOcean Kubernetes.",
    reference: "k8s/",
    status: "Repository artifact",
  },
  {
    title: "Helm Chart",
    purpose: "Packages SmartOps control-plane deployment configuration.",
    method: "Helm install/upgrade workflow.",
    reference: "platform/helm/smartops",
    status: "Repository artifact",
  },
  {
    title: "Grafana / Prometheus",
    purpose: "Observability stack for metrics dashboards and telemetry queries.",
    method: "Prometheus scrape targets and Grafana dashboards.",
    reference: "Configured observability routes",
    status: "Configured",
  },
  {
    title: "External ERP Workloads",
    purpose: "Connects ERP or cloud workloads to SmartOps closed-loop remediation.",
    method: "Expose metrics, logs, traces, or anomaly APIs for SmartOps agents.",
    reference: "Workload-specific integration",
    status: "Available",
  },
];

const API_ENDPOINTS = [
  ["GET /api/dashboard/state", "dashboard state"],
  ["POST /api/scenarios/run", "scenario execution"],
  ["POST /api/actions/trigger", "manual action trigger"],
  ["POST /api/verification", "verification check"],
  ["GET /api/policy/decisions", "policy audit decisions"],
  ["GET /api/services/metrics", "service metrics"],
  ["GET /api/signals/recent", "recent anomaly/RCA signals"],
];

const SETUP_STEPS = [
  "Create or connect DigitalOcean Kubernetes cluster",
  "Configure doctl and kubectl access",
  "Create/use namespace smartops-dev",
  "Build and push SmartOps images to DigitalOcean Container Registry",
  "Deploy observability stack",
  "Deploy ERP workload",
  "Deploy Agent Detect and Agent Diagnose",
  "Deploy Policy Engine",
  "Deploy Orchestrator",
  "Deploy Dashboard API and Dashboard UI",
  "Configure Ingress / Load Balancer routes",
  "Connect workload metrics/logs/traces",
  "Run demo scenarios",
  "Verify closed-loop recovery",
];

const ARTIFACTS = [
  "k8s/",
  "platform/helm/smartops",
  "docs/runbooks/",
  "docs/handbooks/SmartOps Setup Guide.pdf",
  "scripts/run-all.sh",
  "scripts/verify-all.sh",
  "scripts/demo_closedloop.sh",
  "k8s/dashboard-api.yaml",
  "k8s/dashboard-ui.yaml",
  "k8s/orchestrator.yaml",
  "k8s/policy-engine.yaml",
];

const CHECKLIST = [
  "Kubernetes access configured",
  "Namespace created",
  "Images pushed to registry",
  "Services deployed",
  "Prometheus metrics available",
  "Policy engine reachable",
  "Orchestrator reachable",
  "Dashboard API reachable",
  "Dashboard UI exposed through Ingress/Load Balancer",
  "Scenario test completed",
];

const SETUP_PACKAGE_CONTENTS = [
  "Sanitized Kubernetes samples",
  "API contract and integration guide",
  "Policy DSL and notification setup guides",
  "Demo scenario guide and sample environment template",
];

function Integrations({ externalLinks, anomaliesCount, rcasCount }) {
  return (
    <div className="integrations-page">
      <PageHeader
        eyebrow="Connections"
        title="Integrations & Setup"
        description="Connect SmartOps to Kubernetes workloads, observability sources, policy engine, and external ERP systems."
        meta={
          <>
            <span>Platform: DigitalOcean Kubernetes</span>
            <span>Namespace: smartops-dev</span>
            <span>Registry: smartops-registry</span>
            <span>Mode: Cloud deployment</span>
            <span>Setup artifacts: Available in repository</span>
          </>
        }
      />

      <section className="panel integrations-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Integration Surface</p>
            <h2>SmartOps connection points</h2>
          </div>
          <div className="section-heading__meta">
            <span>Registry: registry.digitalocean.com/smartops-registry</span>
          </div>
        </div>

        <div className="integration-card-grid">
          {INTEGRATIONS.map((item) => (
            <article key={item.title} className="integration-card">
              <div className="integration-card__top">
                <h3>{item.title}</h3>
                <span className="service-card__status service-card__status--configured">{item.status}</span>
              </div>
              <p>{item.purpose}</p>
              <div className="integration-detail-list">
                <div>
                  <span>Integration method</span>
                  <strong>{item.method}</strong>
                </div>
                <div>
                  <span>Example path / endpoint</span>
                  <code>{item.reference}</code>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="integrations-split">
        <section className="panel integrations-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">API Contract</p>
              <h2>Frontend API endpoints</h2>
            </div>
          </div>

          <div className="api-contract-list">
            {API_ENDPOINTS.map(([endpoint, purpose]) => (
              <article key={endpoint} className="api-contract-row">
                <code>{endpoint}</code>
                <span>{purpose}</span>
              </article>
            ))}
          </div>
        </section>

        <section className="panel integrations-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">External Systems</p>
              <h2>Workload integration model</h2>
            </div>
          </div>

          <article className="integration-explainer-card">
            <h3>Cloud workload telemetry contract</h3>
            <p>
              Any ERP or cloud workload can integrate with SmartOps by exposing Prometheus metrics,
              logs, traces, or anomaly signal APIs. SmartOps then follows the closed-loop flow:
              Detect to Diagnose to Decide to Act to Verify.
            </p>
            <p>
              Developer scripts can help with local testing, but the deployment target described
              here is DigitalOcean Kubernetes in namespace smartops-dev.
            </p>
          </article>
        </section>
      </section>

      <section className="panel integrations-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Cloud Deployment</p>
            <h2>DigitalOcean Kubernetes setup flow</h2>
          </div>
        </div>

        <div className="setup-flow">
          {SETUP_STEPS.map((step, index) => (
            <article key={step} className="setup-step">
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{step}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="integrations-split">
        <section className="panel integrations-section integrations-download-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Download</p>
              <h2>Setup package</h2>
            </div>
          </div>

          <article className="setup-download-card">
            <div>
              <span className="setup-download-card__badge">Panel-ready ZIP</span>
              <h3>Download Setup Package</h3>
              <p>
                Includes sanitized Kubernetes samples, API contract, integration guide, policy DSL
                guide, notification setup, demo scenario guide, and sample environment template.
              </p>
            </div>
            <ul>
              {SETUP_PACKAGE_CONTENTS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <a
              className="setup-download-card__button"
              href="/smartops-setup-package.zip"
              download
            >
              Download Setup Package
            </a>
          </article>
        </section>

        <section className="panel integrations-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Repository Artifacts</p>
              <h2>Setup artifact references</h2>
            </div>
          </div>

          <div className="artifact-grid">
            {ARTIFACTS.map((artifact) => (
              <code key={artifact} className="artifact-card">
                {artifact}
              </code>
            ))}
          </div>
        </section>

        <section className="panel integrations-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Checklist</p>
              <h2>Integration readiness</h2>
            </div>
          </div>

          <div className="integration-checklist">
            {CHECKLIST.map((item) => (
              <article key={item}>
                <span aria-hidden="true" />
                <p>{item}</p>
              </article>
            ))}
          </div>
        </section>
      </section>

      <section className="panel integrations-section integrations-viva-card">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Examiner View</p>
            <h2>How others integrate with SmartOps</h2>
          </div>
          <div className="section-heading__meta">
            <span>Anomalies observed: {anomaliesCount}</span>
            <span>RCA records observed: {rcasCount}</span>
          </div>
        </div>

        <p>
          External teams can integrate by deploying the SmartOps control-plane services into their
          Kubernetes environment, exposing workload telemetry through Prometheus/logs/traces, and
          configuring policies for approved remediation actions. The setup artifacts are provided
          through Kubernetes manifests, Helm chart files, runbooks, and API contracts.
        </p>

        <div className="tool-grid integrations-observability-grid">
          <article className="tool-card">
            <h3>Grafana</h3>
            <p>{externalLinks.grafana || "Configured observability route"}</p>
          </article>
          <article className="tool-card">
            <h3>Prometheus</h3>
            <p>{externalLinks.prometheus || "Configured metrics route"}</p>
          </article>
          <article className="tool-card">
            <h3>External ERP</h3>
            <p>{externalLinks.odoo || "ERP workload integration endpoint"}</p>
          </article>
        </div>
      </section>
    </div>
  );
}

export default Integrations;
