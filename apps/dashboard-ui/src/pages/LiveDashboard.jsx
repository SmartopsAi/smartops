import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import StatusCard from "../components/StatusCard";

const SUMMARY_DEFINITIONS = [
  { label: "System", aliases: ["system", "service", "deployment"] },
  { label: "Health", aliases: ["health", "status"] },
  { label: "Active Anomaly", aliases: ["active anomaly", "anomaly state", "anomaly"] },
  { label: "RCA State", aliases: ["rca state", "rca"] },
  { label: "Policy", aliases: ["policy"] },
  { label: "Action", aliases: ["action"] },
  { label: "Verification", aliases: ["verification", "verify"] },
  { label: "Replicas", aliases: ["replicas", "replica"] },
];

const SERVICE_DEFINITIONS = [
  { name: "ERP Simulator", system: "erp-simulator", role: "Primary workload" },
  { name: "Odoo", system: "odoo", role: "Primary workload" },
  { name: "PostgreSQL", status: "Configured", role: "Data service" },
  { name: "Agent Detect", status: "Observed", role: "Detection agent" },
  { name: "Agent Diagnose", status: "Observed", role: "RCA agent" },
  { name: "Orchestrator", status: "Observed", role: "Action control" },
  { name: "Policy Engine", status: "Observed", role: "Decision control" },
  { name: "Dashboard API", status: "Observed", role: "Frontend API" },
  { name: "Grafana", status: "Configured", role: "Observability" },
  { name: "Prometheus", status: "Configured", role: "Metrics store" },
];

const normalize = (value) => String(value || "").toLowerCase();

const findSummaryCard = (cards, aliases) =>
  cards.find((card) => {
    const label = normalize(card.label);
    return aliases.some((alias) => label.includes(alias));
  });

const getSystemLabel = (selectedSystem) =>
  selectedSystem === "odoo" ? "Odoo" : "ERP-simulator";

const getReplicaState = (liveSystemState) => {
  if (!liveSystemState) return "Not available";

  const ready =
    liveSystemState.ready_replicas ??
    liveSystemState.readyReplicas ??
    liveSystemState.replicasReady;
  const desired =
    liveSystemState.desired_replicas ??
    liveSystemState.desiredReplicas ??
    liveSystemState.replicasDesired ??
    liveSystemState.replicas;

  if (typeof ready !== "undefined" && typeof desired !== "undefined") {
    return `${ready}/${desired} ready`;
  }

  if (typeof desired !== "undefined") {
    return `${desired} desired`;
  }

  return "Not available";
};

const formatSource = (value) =>
  String(value || "not available")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

function LiveDashboard({
  loading,
  refreshing,
  error,
  environment,
  selectedSystem,
  liveSummaryCards,
  liveSystemState,
  pipelineStages,
  getStageToneClass,
  formatDateTime,
}) {
  const systemLabel =
    liveSystemState?.system ||
    liveSystemState?.service ||
    liveSystemState?.deployment ||
    getSystemLabel(selectedSystem);
  const connected = liveSystemState?.connected === true;
  const connectionLabel = connected ? "Connected" : "Disconnected";
  const refreshLabel = loading ? "Loading" : refreshing ? "Refreshing" : "Ready";
  const replicaSource = liveSystemState?.replicaSource || liveSystemState?.metricsSource || "not available";
  const hasSummaryData = liveSummaryCards.length > 0;
  const healthCards = SUMMARY_DEFINITIONS.map((definition) => {
    const card = findSummaryCard(liveSummaryCards, definition.aliases);
    return {
      label: definition.label,
      value: card?.value ?? "Not available",
      tone: card?.tone ?? "neutral",
    };
  });

  const anomalyCard = findSummaryCard(liveSummaryCards, ["active anomaly", "anomaly state", "anomaly"]);
  const policyCard = findSummaryCard(liveSummaryCards, ["policy"]);
  const verificationCard = findSummaryCard(liveSummaryCards, ["verification", "verify"]);
  const replicaCard = findSummaryCard(liveSummaryCards, ["replicas", "replica"]);
  const replicaState = replicaCard?.value ?? getReplicaState(liveSystemState);

  const liveEvents = [
    {
      title: "Metrics collected from live telemetry",
      value: liveSystemState?.namespace
        ? `${systemLabel} observed in ${liveSystemState.namespace}`
        : `${systemLabel} telemetry observed`,
    },
    {
      title: "Current anomaly state",
      value: anomalyCard?.value ?? "Not available",
    },
    {
      title: "Current policy state",
      value: policyCard?.value ?? "Not available",
    },
    {
      title: "Current verification state",
      value: verificationCard?.value ?? "Not available",
    },
    {
      title: "Kubernetes replica state",
      value: `${replicaState} | Source: ${formatSource(replicaSource)}`,
    },
  ];

  const getServiceStatus = (service) => {
    if (service.system) {
      if (service.system === selectedSystem && connected) return "Connected";
      return "Configured";
    }

    return service.status;
  };

  return (
    <div className="live-dashboard">
      <PageHeader
        eyebrow="Production"
        title="Live Dashboard"
        description="Production view of SmartOps runtime health across Kubernetes ERP workloads."
        meta={
          <>
            <span>Environment: {environment}</span>
            <span>System: {systemLabel}</span>
            <span>Connection: {connectionLabel}</span>
            <span>Refresh: {refreshLabel}</span>
            <span>Replica source: {formatSource(replicaSource)}</span>
            <span>Mode: Live</span>
          </>
        }
      />

      {error ? (
        <section className="panel panel--warning live-dashboard__error">
          <h2>Live API unavailable</h2>
          <p>{error}</p>
          <p>
            The SmartOps backend, local port-forward, or dashboard API may be unavailable. The
            production layout remains visible and will populate when the live API responds.
          </p>
        </section>
      ) : null}

      <section className="panel live-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">System Health</p>
            <h2>Production health overview</h2>
          </div>
          {liveSystemState ? (
            <div className="section-heading__meta">
              <span>{liveSystemState.deployment || systemLabel}</span>
              <span>{liveSystemState.namespace || environment}</span>
              <span>Replica source: {formatSource(replicaSource)}</span>
            </div>
          ) : null}
        </div>

        {loading ? (
          <EmptyState title="Loading production summary">Fetching current SmartOps state.</EmptyState>
        ) : !hasSummaryData ? (
          <EmptyState title="No live summary data">
            No production summary data is available for the selected system.
          </EmptyState>
        ) : (
          <div className="live-health-grid">
            {healthCards.map((card) => (
              <StatusCard key={card.label} label={card.label} value={card.value} tone={card.tone} />
            ))}
          </div>
        )}
      </section>

      <section className="panel live-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Runtime Pipeline</p>
            <h2>Closed-loop runtime pipeline</h2>
          </div>
        </div>

        {loading ? (
          <EmptyState title="Loading runtime pipeline">Fetching live Monitor to Verify state.</EmptyState>
        ) : pipelineStages.length === 0 ? (
          <EmptyState title="No live pipeline data">
            No unbound live pipeline data is available right now.
          </EmptyState>
        ) : (
          <div className="live-pipeline">
            {pipelineStages.map((stage, index) => (
              <article key={stage.key} className={`pipeline-card ${getStageToneClass(stage.status)}`}>
                <div className="pipeline-card__top">
                  <span className="pipeline-card__index">{String(index + 1).padStart(2, "0")}</span>
                  <span className={`badge badge--stage ${getStageToneClass(stage.status)}`}>
                    {stage.status}
                  </span>
                </div>
                <h3>{stage.title}</h3>
                <p>{stage.summary}</p>
                <div className="pipeline-card__meta">
                  <span>Source: {stage.evidenceSource || "Not available"}</span>
                  <span>Updated: {formatDateTime(stage.lastUpdated)}</span>
                </div>
                {stage.details?.length ? (
                  <div className="detail-list">
                    {stage.details.map((detail, detailIndex) => (
                      <div key={`${stage.key}-${detail.label}-${detailIndex}`} className="detail-row">
                        <span className="detail-row__label">{detail.label}</span>
                        <span className="detail-row__value">{detail.value}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="live-dashboard__split">
        <section className="panel live-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Kubernetes</p>
              <h2>Service status</h2>
            </div>
          </div>

          <div className="service-grid">
            {SERVICE_DEFINITIONS.map((service) => {
              const status = getServiceStatus(service);
              return (
                <article key={service.name} className="service-card">
                  <div>
                    <h3>{service.name}</h3>
                    <p>{service.role}</p>
                  </div>
                  <span className={`service-card__status service-card__status--${normalize(status)}`}>
                    {status}
                  </span>
                </article>
              );
            })}
          </div>
        </section>

        <section className="panel live-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Live Events</p>
              <h2>Current event stream</h2>
            </div>
          </div>

          <div className="live-event-list">
            {liveEvents.map((event) => (
              <article key={event.title} className="live-event">
                <span className="live-event__dot" />
                <div>
                  <h3>{event.title}</h3>
                  <p>{event.value}</p>
                </div>
              </article>
            ))}
          </div>
        </section>
      </section>
    </div>
  );
}

export default LiveDashboard;
