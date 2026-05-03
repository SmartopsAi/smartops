import { useMemo, useState } from "react";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "resource", label: "Resource" },
  { key: "error", label: "Error" },
  { key: "guardrail", label: "Guardrail blocked" },
  { key: "p1", label: "P1 priority" },
  { key: "passed", label: "Passed" },
  { key: "pending", label: "Pending / Failed" },
];

const normalize = (value) => String(value || "").toLowerCase();
const display = (value, fallback = "Not available") =>
  value === null || typeof value === "undefined" || value === "" ? fallback : value;

const getWindowId = (item) =>
  item?.windowId || item?.window_id || item?.window || item?.windowID || item?.eventId || item?.event_id || "";

const getTimestamp = (item) => item?.ts_utc || item?.timestamp || item?.ts || item?.created_at || "";

const getTopCause = (rca) => {
  const topCause = rca?.rankedCauses?.[0] || rca?.ranked_causes?.[0];
  return rca?.topCause || rca?.top_cause || topCause?.cause || "Not available";
};

const getTopProbability = (rca) => {
  const topCause = rca?.rankedCauses?.[0] || rca?.ranked_causes?.[0];
  return rca?.probability ?? topCause?.probability ?? "Not available";
};

const buildEvidenceIncident = ({ lastAnomalyEvidence, formatDateTime, humanizePolicyLabel, humanizeActionLabel }) => {
  if (!lastAnomalyEvidence) return null;

  const policy = lastAnomalyEvidence.policy || {};
  const action = lastAnomalyEvidence.action || {};
  const verification = lastAnomalyEvidence.verification || {};
  const rca = lastAnomalyEvidence.rca || {};
  const windowId = getWindowId(lastAnomalyEvidence) || lastAnomalyEvidence.eventId || "last-anomaly";

  return {
    id: `last-${windowId}`,
    source: "Preserved anomaly evidence",
    windowId,
    timestamp: getTimestamp(lastAnomalyEvidence),
    detectedAt: formatDateTime(getTimestamp(lastAnomalyEvidence)),
    type: String(lastAnomalyEvidence.type || "unknown").toUpperCase(),
    service: display(lastAnomalyEvidence.service),
    risk: display(lastAnomalyEvidence.risk || lastAnomalyEvidence.severity),
    score: display(lastAnomalyEvidence.score),
    rca: getTopCause(rca),
    rcaProbability: getTopProbability(rca),
    policy: humanizePolicyLabel(policy.policy, policy.guardrail),
    priority: policy.priority_label || policy.priority || "Not available",
    priorityScore: policy.priority_score ?? "Not available",
    action: humanizeActionLabel(action.type, policy.decision, policy.guardrail),
    verification: verification.status || "Not available",
    result:
      verification.overall === true
        ? "Passed"
        : verification.overall === false
        ? "Failed"
        : "Pending / Not available",
    guardrail: policy.guardrail || "",
    decision: policy.decision || "Not available",
    detection: lastAnomalyEvidence.detection,
    actionDetails: action,
    verificationDetails: verification,
    raw: lastAnomalyEvidence,
  };
};

const buildScenarioIncident = ({ currentScenarioEvidence, selectedPp2ScenarioKey, selectedWindowId }) => {
  if (!currentScenarioEvidence || !selectedWindowId) return null;

  return {
    id: `scenario-${selectedWindowId}`,
    source: "Selected/bound incident reference",
    windowId: selectedWindowId,
    scenarioKey: selectedPp2ScenarioKey,
    timestamp: currentScenarioEvidence.observedAt,
    detectedAt: display(currentScenarioEvidence.observedAt),
    type: display(currentScenarioEvidence.anomalyType),
    service: display(currentScenarioEvidence.service),
    risk: "Not available",
    score: "Not available",
    rca: display(currentScenarioEvidence.rcaCause),
    rcaProbability: display(currentScenarioEvidence.rcaProbability),
    policy: display(currentScenarioEvidence.policy),
    priority: "Not available",
    priorityScore: "Not available",
    action: display(currentScenarioEvidence.action),
    verification:
      typeof currentScenarioEvidence.verifyRequested === "boolean"
        ? currentScenarioEvidence.verifyRequested
          ? "Requested"
          : "Not requested"
        : "Not available",
    result: currentScenarioEvidence.decision === "blocked" ? "Guardrail / no execution" : "Use linked dashboard evidence when available",
    guardrail: currentScenarioEvidence.guardrail || "",
    decision: display(currentScenarioEvidence.decision),
    actionDetails: {
      type: currentScenarioEvidence.action,
      targetReplicas: currentScenarioEvidence.targetReplicas,
    },
    verificationDetails: {
      verifyRequested: currentScenarioEvidence.verifyRequested,
    },
  };
};

function EvidenceTimeline({
  anomalies,
  rcas,
  latestPolicyDecision,
  latestAnomaly,
  latestRca,
  verification,
  lastAnomalyEvidence,
  anomalyHistory,
  currentScenarioEvidence,
  selectedWindowId,
  selectedPp2ScenarioKey,
  onReviewIncident,
  formatDateTime,
  humanizePolicyLabel,
  humanizeActionLabel,
}) {
  const [activeFilter, setActiveFilter] = useState("all");
  const [selectedIncidentId, setSelectedIncidentId] = useState("");

  const incidents = useMemo(() => {
    const rcaByWindow = new Map();
    [...rcas, latestRca].filter(Boolean).forEach((rca) => {
      const windowId = getWindowId(rca);
      if (windowId) {
        rcaByWindow.set(String(windowId), rca);
      }
    });

    const policyWindowId = getWindowId(latestPolicyDecision);
    const latestAnomalyWindowId = getWindowId(latestAnomaly);
    const rows = [];
    const seen = new Set();

    const addIncident = (incident) => {
      if (!incident) return;
      const key = incident.windowId ? String(incident.windowId) : incident.id;
      if (seen.has(key)) return;
      seen.add(key);
      rows.push(incident);
    };

    const anomalySources = [...anomalies, latestAnomaly, ...anomalyHistory].filter(Boolean);

    anomalySources.forEach((anomaly, index) => {
      const windowId = getWindowId(anomaly) || `anomaly-${index}`;
      const matchingRca = rcaByWindow.get(String(windowId));
      const policyApplies =
        (selectedWindowId && String(windowId) === String(selectedWindowId)) ||
        (policyWindowId && String(windowId) === String(policyWindowId)) ||
        (latestAnomalyWindowId && String(windowId) === String(latestAnomalyWindowId));
      const actionPlan = latestPolicyDecision?.action_plan || {};

      addIncident({
        id: `anomaly-${windowId}`,
        source: "Dashboard evidence",
        windowId,
        timestamp: getTimestamp(anomaly),
        detectedAt: formatDateTime(getTimestamp(anomaly)),
        type: String(anomaly.type || "unknown").toUpperCase(),
        service: display(anomaly.service || anomaly.svc),
        risk: display(anomaly.risk || anomaly.severity),
        score: display(anomaly.score),
        rca: matchingRca ? getTopCause(matchingRca) : "Not available",
        rcaProbability: matchingRca ? getTopProbability(matchingRca) : "Not available",
        policy: policyApplies
          ? humanizePolicyLabel(latestPolicyDecision?.policy, latestPolicyDecision?.guardrail_reason)
          : "Not available",
        priority: policyApplies
          ? latestPolicyDecision?.priority_label || latestPolicyDecision?.priority || "Not available"
          : "Not available",
        priorityScore: policyApplies ? latestPolicyDecision?.priority_score ?? "Not available" : "Not available",
        action: policyApplies
          ? humanizeActionLabel(actionPlan.type, latestPolicyDecision?.decision, latestPolicyDecision?.guardrail_reason)
          : "Not available",
        verification: policyApplies ? verification?.status || "Not available" : "Not available",
        result: policyApplies
          ? verification?.overall === true
            ? "Passed"
            : verification?.overall === false
            ? "Failed"
            : "Pending / Not available"
          : "Not available",
        guardrail: policyApplies ? latestPolicyDecision?.guardrail_reason || "" : "",
        decision: policyApplies ? latestPolicyDecision?.decision || "Not available" : "Not available",
        detection: anomaly.detection,
        actionDetails: policyApplies ? actionPlan : {},
        verificationDetails: policyApplies ? verification || {} : {},
        raw: anomaly,
      });
    });

    addIncident(
      buildEvidenceIncident({
        lastAnomalyEvidence,
        formatDateTime,
        humanizePolicyLabel,
        humanizeActionLabel,
      })
    );

    addIncident(
      buildScenarioIncident({
        currentScenarioEvidence,
        selectedPp2ScenarioKey,
        selectedWindowId,
      })
    );

    return rows.sort((a, b) => {
      const aTime = new Date(a.timestamp).getTime();
      const bTime = new Date(b.timestamp).getTime();
      if (Number.isNaN(aTime) && Number.isNaN(bTime)) return 0;
      if (Number.isNaN(aTime)) return 1;
      if (Number.isNaN(bTime)) return -1;
      return bTime - aTime;
    });
  }, [
    anomalies,
    rcas,
    latestPolicyDecision,
    latestAnomaly,
    latestRca,
    verification,
    lastAnomalyEvidence,
    anomalyHistory,
    currentScenarioEvidence,
    selectedWindowId,
    selectedPp2ScenarioKey,
    formatDateTime,
    humanizePolicyLabel,
    humanizeActionLabel,
  ]);

  const filteredIncidents = useMemo(() => {
    return incidents.filter((incident) => {
      const type = normalize(incident.type);
      const guardrail = normalize(incident.guardrail || incident.decision || incident.action);
      const priority = normalize(incident.priority);
      const result = normalize(incident.result || incident.verification);

      if (activeFilter === "resource") return type.includes("resource");
      if (activeFilter === "error") return type.includes("error");
      if (activeFilter === "guardrail") return guardrail.includes("blocked") || guardrail.includes("guardrail");
      if (activeFilter === "p1") return priority.includes("p1") || priority.includes("critical");
      if (activeFilter === "passed") return result.includes("passed") || result.includes("success");
      if (activeFilter === "pending") {
        return result.includes("pending") || result.includes("failed") || result.includes("not available");
      }
      return true;
    });
  }, [activeFilter, incidents]);

  const selectedIncident =
    filteredIncidents.find((incident) => incident.id === selectedIncidentId) || filteredIncidents[0] || null;
  const activeFilterLabel = FILTERS.find((filter) => filter.key === activeFilter)?.label || "All";

  return (
    <div className="evidence-page">
      <PageHeader
        eyebrow="Audit"
        title="Evidence Timeline"
        description="Audit trail of anomaly windows, RCA results, policy decisions, actions, and verification outcomes."
        meta={
          <>
            <span>Total windows: {incidents.length}</span>
            <span>Selected window: {selectedIncident?.windowId || selectedWindowId || "None"}</span>
            <span>Active filter: {activeFilterLabel}</span>
            <span>Source: Dashboard evidence</span>
          </>
        }
      />

      <section className="panel evidence-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Filters</p>
            <h2>Incident evidence windows</h2>
          </div>
        </div>

        <div className="evidence-filters" aria-label="Evidence filters">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              type="button"
              className={`action-button ${activeFilter === filter.key ? "action-button--primary" : ""}`}
              onClick={() => setActiveFilter(filter.key)}
            >
              {filter.label}
            </button>
          ))}
        </div>

        {filteredIncidents.length === 0 ? (
          <EmptyState title="No incident evidence available yet. Run a Demo Lab scenario or wait for live anomaly detection." />
        ) : (
          <div className="evidence-table" role="table" aria-label="Incident evidence">
            <div className="evidence-table__header" role="row">
              <span>Window ID</span>
              <span>Type</span>
              <span>Service</span>
              <span>Risk</span>
              <span>RCA</span>
              <span>Policy</span>
              <span>Priority</span>
              <span>Action</span>
              <span>Verification</span>
              <span>Result</span>
            </div>

            {filteredIncidents.map((incident) => (
              <button
                key={incident.id}
                type="button"
                className={`evidence-row ${selectedIncident?.id === incident.id ? "evidence-row--active" : ""}`}
                onClick={() => setSelectedIncidentId(incident.id)}
                role="row"
              >
                <span data-label="Window ID">{display(incident.windowId)}</span>
                <span data-label="Type">{display(incident.type)}</span>
                <span data-label="Service">{display(incident.service)}</span>
                <span data-label="Risk">{display(incident.risk)}</span>
                <span data-label="RCA">{display(incident.rca)}</span>
                <span data-label="Policy">{display(incident.policy)}</span>
                <span data-label="Priority">{display(incident.priority)}</span>
                <span data-label="Action">{display(incident.action)}</span>
                <span data-label="Verification">{display(incident.verification)}</span>
                <span data-label="Result">{display(incident.result)}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      {selectedIncident ? (
        <section className="panel evidence-section evidence-detail">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Incident Detail</p>
              <h2>Window {selectedIncident.windowId}</h2>
            </div>
            <div className="section-heading__meta">
              <span>{selectedIncident.source}</span>
              <span>{selectedIncident.detectedAt}</span>
            </div>
          </div>

          <div className="evidence-detail-grid">
            <article className="evidence-detail-card">
              <h3>Detection details</h3>
              <p>Type: {display(selectedIncident.type)}</p>
              <p>Service: {display(selectedIncident.service)}</p>
              <p>Risk: {display(selectedIncident.risk)}</p>
              <p>Score: {display(selectedIncident.score)}</p>
              {selectedIncident.detection ? (
                <p>
                  Detection: Statistical = {String(selectedIncident.detection.statistical ?? false)}, Isolation
                  Forest = {String(selectedIncident.detection.isolation_forest ?? false)}
                </p>
              ) : null}
            </article>

            <article className="evidence-detail-card">
              <h3>RCA details</h3>
              <p>Top cause: {display(selectedIncident.rca)}</p>
              <p>Probability: {display(selectedIncident.rcaProbability)}</p>
            </article>

            <article className="evidence-detail-card">
              <h3>Policy decision</h3>
              <p>Policy: {display(selectedIncident.policy)}</p>
              <p>Decision: {display(selectedIncident.decision)}</p>
              <p>Guardrail: {display(selectedIncident.guardrail, "Not applicable")}</p>
            </article>

            <article className="evidence-detail-card">
              <h3>Priority Matrix</h3>
              <p>Label: {display(selectedIncident.priority)}</p>
              <p>Score: {display(selectedIncident.priorityScore)}</p>
            </article>

            <article className="evidence-detail-card">
              <h3>Action details</h3>
              <p>Action: {display(selectedIncident.action)}</p>
              <p>Type: {display(selectedIncident.actionDetails?.type)}</p>
              <p>
                Target replicas:{" "}
                {display(selectedIncident.actionDetails?.scale?.replicas ?? selectedIncident.actionDetails?.targetReplicas)}
              </p>
            </article>

            <article className="evidence-detail-card">
              <h3>Verification result</h3>
              <p>Status: {display(selectedIncident.verification)}</p>
              <p>Result: {display(selectedIncident.result)}</p>
              <p>
                Ready / Desired replicas:{" "}
                {display(selectedIncident.verificationDetails?.ready_replicas, "-")} /{" "}
                {display(selectedIncident.verificationDetails?.desired_replicas, "-")}
              </p>
              <p>Message: {display(selectedIncident.verificationDetails?.message)}</p>
            </article>
          </div>

          <div className="evidence-detail-actions">
            <button
              type="button"
              className="action-button action-button--primary"
              onClick={() => onReviewIncident?.(selectedIncident.windowId, selectedIncident.scenarioKey)}
              disabled={!selectedIncident.windowId}
            >
              Review in Demo Lab
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default EvidenceTimeline;
