import { useState } from "react";
import LoadingPulse from "../components/LoadingPulse";
import PageHeader from "../components/PageHeader";
import { runUnmatchedAnomalyDemo } from "../lib/api";

const SCENARIOS = [
  {
    key: "scenario-1",
    title: "Scenario 1: Resource anomaly -> Scale up",
    anomaly: "RESOURCE",
    rca: "Resource Saturation",
    policy: "Resource anomaly scale-up",
    action: "Scale ERP simulator to 4 replicas",
    verification: "Deployment reaches desired replica count",
  },
  {
    key: "scenario-2",
    title: "Scenario 2: Error anomaly -> Restart",
    anomaly: "ERROR",
    rca: "Service Timeout",
    policy: "Error anomaly restart",
    action: "Restart ERP simulator deployment",
    verification: "Deployment returns to ready state",
  },
  {
    key: "scenario-3",
    title: "Scenario 3: Repeated restart -> Guardrail blocked",
    anomaly: "ERROR",
    rca: "Repeated service instability",
    policy: "Restart cooldown guardrail",
    action: "Block repeated restart",
    verification: "Guardrail prevents disruptive repeat action",
  },
];

const copyWindowId = async (windowId) => {
  if (!windowId || !navigator.clipboard) return;
  await navigator.clipboard.writeText(windowId);
};

const scrollToEvidence = () => {
  document.getElementById("demo-evidence")?.scrollIntoView({ behavior: "smooth", block: "start" });
};

const firstAvailable = (...values) => values.find((value) => value !== null && typeof value !== "undefined" && value !== "");

function DemoDashboard({
  loading,
  selectedSystem,
  selectedWindowId,
  selectedPp2ScenarioKey,
  latestPolicyDecision,
  latestAnomaly,
  latestRca,
  verification,
  lastAnomalyEvidence,
  evidencePriorityLabel,
  evidencePriorityScore,
  evidencePolicyRank,
  evidenceRca,
  evidenceAffectedService,
  evidencePolicy,
  evidenceAction,
  evidenceTarget,
  evidenceVerification,
  evidenceVerificationResult,
  anomalyHistory,
  pipelineStages,
  currentScenarioEvidence,
  isOdoo,
  runningScenario,
  runningManualAction,
  runLiveScenario,
  runManualDevopsAction,
  clearScenarioBinding,
  refreshDashboard,
  formatDateTime,
  humanizePolicyLabel,
  humanizeActionLabel,
  getStageToneClass,
}) {
  const [unmatchedAdminKey, setUnmatchedAdminKey] = useState("");
  const [runningUnmatchedDemo, setRunningUnmatchedDemo] = useState(false);
  const [unmatchedDemoResult, setUnmatchedDemoResult] = useState(null);
  const [unmatchedDemoError, setUnmatchedDemoError] = useState("");

  const selectedScenarioLabel = selectedPp2ScenarioKey || "None";
  const systemLabel = selectedSystem === "odoo" ? "Odoo" : "ERP-simulator";
  const latestBoundWindowId = firstAvailable(
    currentScenarioEvidence?.windowIds?.[0],
    selectedWindowId
  );
  const latestBoundObservedAt = firstAvailable(
    currentScenarioEvidence?.observedAt,
    latestPolicyDecision?.ts_utc,
    latestPolicyDecision?.ts
  );
  const topRca = latestRca?.rankedCauses?.[0];
  const resultSummary = {
    windowId: selectedWindowId || "Current live state",
    anomalyType:
      currentScenarioEvidence?.anomalyType ||
      String(latestAnomaly?.type || lastAnomalyEvidence?.type || "").toUpperCase() ||
      "Pending",
    rcaCause:
      currentScenarioEvidence?.rcaCause ||
      topRca?.cause ||
      evidenceRca.topCause ||
      "Pending",
    policy:
      currentScenarioEvidence?.policy ||
      humanizePolicyLabel(latestPolicyDecision?.policy, latestPolicyDecision?.guardrail_reason) ||
      "Pending",
    priorityLabel: evidencePriorityLabel || "Not available",
    action:
      currentScenarioEvidence?.action ||
      humanizeActionLabel(
        latestPolicyDecision?.action_plan?.type,
        latestPolicyDecision?.decision,
        latestPolicyDecision?.guardrail_reason
      ) ||
      "Pending",
    verification:
      verification?.status ||
      evidenceVerification.status ||
      currentScenarioEvidence?.decision ||
      "Pending",
    guardrail:
      currentScenarioEvidence?.guardrail ||
      latestPolicyDecision?.guardrail_reason ||
      evidencePolicy.guardrail ||
      "",
  };
  const unmatchedSignal = unmatchedDemoResult?.generated_signal || {};
  const unmatchedDecision = unmatchedDemoResult?.policy_decision || {};
  const unmatchedRecord = unmatchedDemoResult?.unmatched_anomaly || null;

  const handleRunUnmatchedDemo = async () => {
    if (!unmatchedAdminKey.trim()) {
      setUnmatchedDemoError("Admin API key is required to run the unmatched anomaly demo.");
      return;
    }

    try {
      setRunningUnmatchedDemo(true);
      setUnmatchedDemoError("");
      const result = await runUnmatchedAnomalyDemo(unmatchedAdminKey.trim());
      setUnmatchedDemoResult(result);
      await refreshDashboard?.();
    } catch (err) {
      setUnmatchedDemoError(err.message || "Unmatched anomaly demo failed.");
    } finally {
      setRunningUnmatchedDemo(false);
    }
  };

  return (
    <div className="demo-lab">
      <PageHeader
        eyebrow="Demo Lab"
        title="Demo Lab"
        description="Guided SmartOps self-healing scenarios for anomaly detection, RCA, policy decision, action, and verification."
        meta={
          <>
            <span>Mode: Demo</span>
            <span>System: {systemLabel}</span>
            <span>Selected scenario: {selectedScenarioLabel}</span>
            <span>Bound window: {selectedWindowId || "Current live state"}</span>
          </>
        }
      />

      <section className="panel demo-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Scenario Runner</p>
            <h2>Run a guided self-healing scenario</h2>
          </div>
          <div className="section-heading__meta">
            <span>{isOdoo ? "ERP scenarios hidden for Odoo" : "ERP simulator scenarios enabled"}</span>
          </div>
        </div>

        {isOdoo ? (
          <div className="empty-state">
            <h3>Scenario execution is hidden for Odoo</h3>
            <p>Live PP2 scenario execution is intentionally limited to ERP-simulator.</p>
          </div>
        ) : (
          <>
            <div className="demo-scenario-grid">
              {SCENARIOS.map((scenario) => {
                const isSelected = selectedPp2ScenarioKey === scenario.key;
                const isRunning = runningScenario === scenario.key;
                const observedWindowId = isSelected ? latestBoundWindowId : "";
                const evidenceSource = observedWindowId
                  ? "Live policy audit / dashboard state"
                  : "No live evidence observed";

                return (
                  <article
                    key={scenario.key}
                    className={`demo-scenario-card ${isSelected ? "demo-scenario-card--active" : ""}`}
                  >
                    <div className="demo-scenario-card__top">
                      <h3>{scenario.title}</h3>
                      <span className="badge badge--active">{scenario.anomaly}</span>
                    </div>

                    <div className="demo-expectation-list">
                      <div>
                        <span>Expected RCA</span>
                        <strong>{scenario.rca}</strong>
                      </div>
                      <div>
                        <span>Expected policy</span>
                        <strong>{scenario.policy}</strong>
                      </div>
                      <div>
                        <span>Expected action</span>
                        <strong>{scenario.action}</strong>
                      </div>
                      <div>
                        <span>Expected verification</span>
                        <strong>{scenario.verification}</strong>
                      </div>
                      <div>
                        <span>Evidence source</span>
                        <strong>{evidenceSource}</strong>
                      </div>
                      <div>
                        <span>{latestBoundObservedAt && observedWindowId ? "Last observed window" : "Latest observed window"}</span>
                        <strong>{observedWindowId || "No live window observed yet"}</strong>
                      </div>
                      {latestBoundObservedAt && observedWindowId ? (
                        <div>
                          <span>Last observed at</span>
                          <strong>{formatDateTime(latestBoundObservedAt)}</strong>
                        </div>
                      ) : null}
                    </div>

                    <div className="scenario-actions demo-card-actions">
                      <button
                        className="action-button action-button--primary"
                        onClick={() => runLiveScenario(scenario.key)}
                        disabled={Boolean(runningScenario)}
                      >
                        {isRunning ? "Running..." : "Run Scenario"}
                      </button>
                      <button
                        className="action-button"
                        onClick={scrollToEvidence}
                        disabled={!observedWindowId}
                      >
                        View Evidence
                      </button>
                      <button
                        className="action-button"
                        onClick={() => copyWindowId(observedWindowId)}
                        disabled={!observedWindowId}
                      >
                        Copy Window ID
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>

            {runningScenario ? (
              <LoadingPulse activeLabel={`${runningScenario} is moving through the SmartOps loop.`} />
            ) : null}
          </>
        )}
      </section>

      <section className="panel demo-section demo-unmatched-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Scenario 4</p>
            <h2>Unmatched anomaly / policy gap</h2>
          </div>
          <div className="section-heading__meta">
            <span>Admin protected</span>
            <span>Policy Engine evaluation only</span>
          </div>
        </div>

        <article className="demo-unmatched-card">
          <div>
            <span className="badge badge--stage stage-warning">POLICY GAP</span>
            <h3>Scenario 4 - Unmatched anomaly / policy gap</h3>
            <p>
              Triggers an unknown anomaly type that intentionally has no matching policy. SmartOps records it as
              an unmatched anomaly and sends automatic notifications for a newly created record.
            </p>
          </div>

          <div className="demo-admin-inline">
            <label>
              <span>Admin API Key</span>
              <input
                type="password"
                value={unmatchedAdminKey}
                onChange={(event) => setUnmatchedAdminKey(event.target.value)}
                placeholder="Enter admin key for this run"
                autoComplete="off"
              />
            </label>
            <button
              className="action-button action-button--primary"
              type="button"
              onClick={handleRunUnmatchedDemo}
              disabled={runningUnmatchedDemo || !unmatchedAdminKey.trim()}
            >
              {runningUnmatchedDemo ? "Running unmatched demo..." : "Run Unmatched Anomaly Demo"}
            </button>
          </div>

          {unmatchedDemoError ? <p className="demo-error-text">{unmatchedDemoError}</p> : null}

          {unmatchedDemoResult ? (
            <div className="demo-unmatched-result">
              <div>
                <span>Decision</span>
                <strong>{unmatchedDecision.decision || "Not available"}</strong>
              </div>
              <div>
                <span>Reason</span>
                <strong>{unmatchedDecision.reason || "No policy matched"}</strong>
              </div>
              <div>
                <span>Generated test window</span>
                <strong>{unmatchedSignal.windowId || "Not available"}</strong>
              </div>
              <div>
                <span>Anomaly type</span>
                <strong>{unmatchedSignal.anomaly?.type || "Not available"}</strong>
              </div>
              <div>
                <span>Risk / score</span>
                <strong>
                  {unmatchedSignal.metadata?.risk || "Not available"} / {unmatchedSignal.anomaly?.score ?? "Not available"}
                </strong>
              </div>
              <div>
                <span>RCA cause</span>
                <strong>
                  {unmatchedSignal.rca?.cause || "Not available"} / {unmatchedSignal.rca?.probability ?? "Not available"}
                </strong>
              </div>
              <div>
                <span>Unmatched anomaly ID</span>
                <strong>{unmatchedRecord?.id || "Pending in policy store"}</strong>
              </div>
              <div>
                <span>Expected effect</span>
                <strong>{unmatchedDemoResult.expected_effect || "Unmatched record and notification trigger expected"}</strong>
              </div>
            </div>
          ) : null}

          <p className="demo-next-step">
            Next step: Open Policy Studio - Unmatched Anomalies - Select this anomaly - Generate AI Draft.
          </p>
        </article>
      </section>

      <section className="demo-lab__split">
        <section className="panel demo-section demo-result-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Demo Result</p>
              <h2>Scenario result summary</h2>
            </div>
          </div>

          <div className="demo-result-grid">
            <div>
              <span>Window ID</span>
              <strong>{resultSummary.windowId}</strong>
            </div>
            <div>
              <span>Anomaly type</span>
              <strong>{resultSummary.anomalyType || "Pending"}</strong>
            </div>
            <div>
              <span>RCA cause</span>
              <strong>{resultSummary.rcaCause}</strong>
            </div>
            <div>
              <span>Policy</span>
              <strong>{resultSummary.policy}</strong>
            </div>
            <div>
              <span>Priority label</span>
              <strong>{resultSummary.priorityLabel}</strong>
            </div>
            <div>
              <span>Action</span>
              <strong>{resultSummary.action}</strong>
            </div>
            <div>
              <span>Verification</span>
              <strong>{resultSummary.verification}</strong>
            </div>
            <div>
              <span>Guardrail</span>
              <strong>{resultSummary.guardrail || "Not applicable"}</strong>
            </div>
          </div>
        </section>

        <section className="panel demo-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Controls</p>
              <h2>Reset and refresh</h2>
            </div>
          </div>

          <div className="scenario-actions demo-control-actions">
            <button className="action-button" onClick={clearScenarioBinding} disabled={isOdoo || !selectedWindowId}>
              Return to current live state
            </button>
            <button
              className="action-button"
              onClick={() => runManualDevopsAction("baseline-reset")}
              disabled={isOdoo || runningManualAction === "baseline-reset"}
            >
              {runningManualAction === "baseline-reset"
                ? "Resetting baseline..."
                : "Reset ERP simulator baseline"}
            </button>
            <button className="action-button action-button--primary" onClick={refreshDashboard}>
              Refresh evidence / Refresh dashboard
            </button>
          </div>
        </section>
      </section>

      {selectedWindowId ? (
        <section className="panel demo-section demo-review-banner">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Section A1</p>
              <h2>Incident review mode active</h2>
            </div>
            <div className="section-heading__meta">
              <span>Resolved incident evidence</span>
              <span>Window: {selectedWindowId}</span>
            </div>
          </div>

          <div className="empty-state">
            <h3>You are reviewing a resolved incident. Live system state is available in the Live Dashboard.</h3>
            <p>
              The evidence below is intentionally preserved for the selected incident window,
              including anomaly detection, RCA, policy decision, remediation action, and verification.
            </p>
          </div>
        </section>
      ) : null}

      <section className="panel demo-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Section B</p>
            <h2>Closed-loop pipeline</h2>
          </div>
        </div>

        {loading ? (
          <div className="empty-state">
            <h3>Loading pipeline</h3>
            <p>Fetching live Monitor to Verify state.</p>
          </div>
        ) : pipelineStages.length === 0 ? (
          <div className="empty-state">
            <h3>No pipeline data</h3>
            <p>No live closed-loop pipeline data is available right now.</p>
          </div>
        ) : (
          <div className="pipeline-grid">
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

      <section id="demo-evidence" className="panel demo-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Section A2</p>
            <h2>Last anomaly evidence</h2>
          </div>
          <div className="section-heading__meta">
            <span>Preserved after auto-healing</span>
          </div>
        </div>

        {!lastAnomalyEvidence ? (
          <div className="empty-state">
            <h3>No previous anomaly recorded</h3>
            <p>
              Once an anomaly is detected, SmartOps will preserve the last anomaly here even after
              the live system returns to normal.
            </p>
          </div>
        ) : (
          <div className="scenario-grid demo-evidence-grid">
            <article className="scenario-card demo-evidence-card">
              <h3>
                {String(lastAnomalyEvidence.type || "Unknown").toUpperCase()} anomaly on{" "}
                {lastAnomalyEvidence.service || "unknown service"}
              </h3>

              <div className="pipeline-card__meta">
                <span className="badge badge--active">Policy Priority: {evidencePriorityLabel}</span>
                <span>Priority Matrix Score: {evidencePriorityScore}</span>
                <span>Policy Rank: {evidencePolicyRank}</span>
              </div>

              <div className="demo-evidence-sections">
                <section>
                  <h4>Detection</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Event ID</span>
                      <span className="detail-row__value">{lastAnomalyEvidence.eventId || "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Severity / Risk</span>
                      <span className="detail-row__value">
                        {lastAnomalyEvidence.severity || "Not available"} /{" "}
                        {lastAnomalyEvidence.risk || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Detected at</span>
                      <span className="detail-row__value">
                        {formatDateTime(lastAnomalyEvidence.ts_utc || lastAnomalyEvidence.timestamp)}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Score / Source</span>
                      <span className="detail-row__value">
                        {lastAnomalyEvidence.score ?? "Not available"} /{" "}
                        {lastAnomalyEvidence.source || "agent-detect"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Detection</span>
                      <span className="detail-row__value">
                        Statistical = {String(lastAnomalyEvidence.detection?.statistical ?? false)},{" "}
                        Isolation Forest = {String(lastAnomalyEvidence.detection?.isolation_forest ?? false)}
                      </span>
                    </div>
                  </div>
                </section>

                <section>
                  <h4>Root Cause Analysis</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Top cause</span>
                      <span className="detail-row__value">{evidenceRca.topCause || "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Confidence</span>
                      <span className="detail-row__value">{evidenceRca.confidence ?? "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Probability</span>
                      <span className="detail-row__value">{evidenceRca.probability ?? "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Affected service</span>
                      <span className="detail-row__value">{evidenceAffectedService}</span>
                    </div>
                  </div>
                </section>

                <section>
                  <h4>Policy Decision and Priority Matrix</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Decision</span>
                      <span className="detail-row__value">{evidencePolicy.decision || "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Policy</span>
                      <span className="detail-row__value">
                        {humanizePolicyLabel(evidencePolicy.policy, evidencePolicy.guardrail)}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Guardrail</span>
                      <span className="detail-row__value">{evidencePolicy.guardrail || "allowed"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Priority label</span>
                      <span className="detail-row__value">
                        <strong>{evidencePriorityLabel}</strong>
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Priority score</span>
                      <span className="detail-row__value">{evidencePriorityScore}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Execution mode</span>
                      <span className="detail-row__value">{evidencePolicy.execution_mode || "Not available"}</span>
                    </div>
                  </div>
                </section>

                <section>
                  <h4>Remediation Action</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Action type</span>
                      <span className="detail-row__value">
                        {humanizeActionLabel(evidenceAction.type, evidencePolicy.decision, evidencePolicy.guardrail)}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Target</span>
                      <span className="detail-row__value">
                        {evidenceTarget.namespace || "Not available"}/{evidenceTarget.name || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Target kind</span>
                      <span className="detail-row__value">{evidenceTarget.kind || "Deployment"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Target replicas</span>
                      <span className="detail-row__value">{evidenceAction.scale?.replicas ?? "Not applicable"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Dry run / Verify</span>
                      <span className="detail-row__value">
                        {String(evidenceAction.dry_run ?? false)} / {String(evidenceAction.verify ?? false)}
                      </span>
                    </div>
                  </div>
                </section>

                <section>
                  <h4>Verification Result</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Status</span>
                      <span className="detail-row__value">{evidenceVerification.status || "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Result</span>
                      <span className="detail-row__value">{evidenceVerificationResult}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Ready / Desired replicas</span>
                      <span className="detail-row__value">
                        {evidenceVerification.ready_replicas ?? "-"} /{" "}
                        {evidenceVerification.desired_replicas ?? "-"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Source</span>
                      <span className="detail-row__value">{evidenceVerification.source || "Not available"}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Message</span>
                      <span className="detail-row__value">
                        {evidenceVerification.message || "No verification message available"}
                      </span>
                    </div>
                  </div>
                </section>
              </div>

              <p>
                Explanation: This evidence is intentionally retained for audit, troubleshooting, and
                viva demonstration even after the live system has already recovered.
              </p>
            </article>

            <article className="scenario-card scenario-card--muted">
              <h3>Recent anomaly history</h3>
              {anomalyHistory.length === 0 ? (
                <p>No history records available.</p>
              ) : (
                anomalyHistory.slice(0, 5).map((event) => (
                  <p key={event.eventId || event.timestamp}>
                    {formatDateTime(event.ts_utc || event.timestamp)} -{" "}
                    {String(event.type || "unknown").toUpperCase()} / {event.severity || "unknown"} /{" "}
                    {event.service || "unknown"}
                  </p>
                ))
              )}
            </article>
          </div>
        )}
      </section>
    </div>
  );
}

export default DemoDashboard;
