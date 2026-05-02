import { useEffect, useMemo, useState } from "react";
import "./App.css";
import "./styles/layout.css";
import "./styles/dock.css";
import "./styles/cards.css";
import "./styles/pages.css";
import HoverDock from "./components/HoverDock";
import DemoDashboard from "./pages/DemoDashboard";
import EvidenceTimeline from "./pages/EvidenceTimeline";
import Integrations from "./pages/Integrations";
import LiveDashboard from "./pages/LiveDashboard";
import PolicyStudio from "./pages/PolicyStudio";
import Settings from "./pages/Settings";
import {
  DASHBOARD_ENV,
  DASHBOARD_MODES,
  DASHBOARD_SYSTEMS,
  EXTERNAL_LINKS,
  REFRESH_INTERVALS,
} from "./lib/config";
import {
  getDashboardState,
  runScenario,
  triggerAction,
  verifyDeployment,
} from "./lib/api";


const getInitialDashboardUrlState = () => {
  const params = new URLSearchParams(window.location.search);

  const system = params.get("system") || "erp-simulator";
  const scenarioKey = params.get("scenario_key") || "";
  const windowId = params.get("window_id") || "";

  return {
    system,
    scenarioKey,
    windowId,
  };
};

const syncDashboardUrlState = ({ system, scenarioKey, windowId }) => {
  const params = new URLSearchParams(window.location.search);

  if (system && system !== "erp-simulator") {
    params.set("system", system);
  } else {
    params.delete("system");
  }

  if (system === "erp-simulator" && scenarioKey) {
    params.set("scenario_key", scenarioKey);
  } else {
    params.delete("scenario_key");
  }

  if (system === "erp-simulator" && windowId) {
    params.set("window_id", windowId);
  } else {
    params.delete("window_id");
  }

  const nextQuery = params.toString();
  const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}`;
  window.history.replaceState({}, "", nextUrl);
};

function App() {
  const [activePage, setActivePage] = useState("live");
  const [selectedMode, setSelectedMode] = useState("live");
  const [selectedSystem, setSelectedSystem] = useState(() => getInitialDashboardUrlState().system);
  const [dashboardState, setDashboardState] = useState(null);
  const [liveDashboardState, setLiveDashboardState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [runningScenario, setRunningScenario] = useState("");
  const [runningManualAction, setRunningManualAction] = useState("");
  const [selectedPp2ScenarioKey, setSelectedPp2ScenarioKey] = useState(() => getInitialDashboardUrlState().scenarioKey);
  const [selectedWindowId, setSelectedWindowId] = useState(() => getInitialDashboardUrlState().windowId);
  const [lastActionResult, setLastActionResult] = useState(null);
  const [lastVerificationResult, setLastVerificationResult] = useState(null);

  const loadDashboardState = async (showFullLoading = false, overrides = {}) => {
    try {
      if (showFullLoading) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      const scenarioKey =
        selectedSystem === "erp-simulator"
          ? overrides.scenarioKey ?? selectedPp2ScenarioKey
          : "";

      const windowId =
        selectedSystem === "erp-simulator"
          ? overrides.windowId ?? selectedWindowId
          : "";

      const isBoundReview = Boolean(scenarioKey || windowId);
      const livePayload = await getDashboardState(selectedSystem, 20, "", "");
      const payload = isBoundReview
        ? await getDashboardState(selectedSystem, 20, scenarioKey, windowId)
        : livePayload;

      setLiveDashboardState(livePayload);
      setDashboardState(payload);
      setError("");
    } catch (err) {
      setDashboardState(null);
      setLiveDashboardState(null);
      setError(err.message || "Failed to load dashboard state.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadDashboardState(true);
  }, [selectedSystem, selectedPp2ScenarioKey, selectedWindowId]);

  useEffect(() => {
    const intervalMs = REFRESH_INTERVALS[selectedMode] || 10000;
    const timer = setInterval(() => {
      loadDashboardState(false);
    }, intervalMs);

    return () => clearInterval(timer);
  }, [selectedMode, selectedSystem, selectedPp2ScenarioKey, selectedWindowId]);

  useEffect(() => {
    syncDashboardUrlState({
      system: selectedSystem,
      scenarioKey: selectedPp2ScenarioKey,
      windowId: selectedWindowId,
    });
  }, [selectedSystem, selectedPp2ScenarioKey, selectedWindowId]);


  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const runVerificationWithRetry = async (payload, maxAttempts = 4) => {
    let lastResult = null;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const result = await verifyDeployment(payload);
        lastResult = result;

        if (String(result?.status || "").toUpperCase() === "SUCCESS") {
          return result;
        }
      } catch (err) {
        lastResult = {
          status: "ERROR",
          message: err.message || "Verification request failed.",
        };
      }

      if (attempt < maxAttempts) {
        await sleep(3000);
      }
    }

    return lastResult;
  };

  const runLiveScenario = async (scenarioKey) => {
    if (selectedSystem !== "erp-simulator") {
      setActionError("Live scenario execution is available only for ERP-simulator.");
      return;
    }

    try {
      setRunningScenario(scenarioKey);
      setActionError("");
      setActionMessage("");
      setLastActionResult(null);
      setLastVerificationResult(null);
      setSelectedPp2ScenarioKey(scenarioKey);
      setSelectedWindowId("");

      const result = await runScenario({
        scenarioKey,
        system: selectedSystem,
      });

      if (result.status !== "ok") {
        throw new Error(result.message || "Scenario execution failed.");
      }

      if (!result.windowId) {
        throw new Error("Scenario ran but no bound windowId was returned from the backend.");
      }
    setSelectedWindowId(result.windowId);
    const scenarioLabel =
      scenarioKey === "scenario-1"
        ? "Scenario 1"
        : scenarioKey === "scenario-2"
        ? "Scenario 2"
        : "Scenario 3";

    const decision = String(result?.policy?.decision || "").toLowerCase();
    const guardrail = result?.policy?.guardrail_reason || result?.policy?.guardrail;

    if (scenarioKey === "scenario-3" && decision === "blocked") {
      setActionMessage(
        `${scenarioLabel} completed and the dashboard is now bound to live window ${result.windowId}. Repeated restart was blocked by guardrails${guardrail ? ` (${guardrail})` : ""}.`
      );
    } else {
      setActionMessage(
        `${scenarioLabel} completed and the dashboard is now bound to live window ${result.windowId}.`
      );
    }

      await loadDashboardState(false, {
        scenarioKey,
        windowId: result.windowId,
      });

      for (let attempt = 0; attempt < 2; attempt += 1) {
        await sleep(2500);
        await loadDashboardState(false, {
          scenarioKey,
          windowId: result.windowId,
        });
      }
    } catch (err) {
      setActionError(err.message || "Scenario execution failed.");
    } finally {
      setRunningScenario("");
    }
  };

  const runManualDevopsAction = async (actionKey) => {
    if (selectedSystem !== "erp-simulator") {
      setActionError("Manual DevOps controls are available only for ERP-simulator.");
      return;
    }

    try {
      setRunningManualAction(actionKey);
      setActionError("");
      setActionMessage("");
      setLastActionResult(null);
      setLastVerificationResult(null);

      if (actionKey === "manual-scale") {
        const actionResult = await triggerAction({
          action: "scale",
          namespace: "smartops-dev",
          name: "smartops-erp-simulator",
          replicas: 4,
          dry_run: false,
        });

        const verificationResult = await runVerificationWithRetry({
          namespace: "smartops-dev",
          deployment: "smartops-erp-simulator",
          expected_replicas: 4,
        });

        setLastActionResult(actionResult);
        setLastVerificationResult(verificationResult);
        setActionMessage("Manual scale action completed with live action and verification results.");
      } else if (actionKey === "manual-restart") {
        const actionResult = await triggerAction({
          action: "restart",
          namespace: "smartops-dev",
          name: "smartops-erp-simulator",
          dry_run: false,
        });

        const verificationResult = await runVerificationWithRetry({
          namespace: "smartops-dev",
          deployment: "smartops-erp-simulator",
          expected_replicas: 3,
        });

        setLastActionResult(actionResult);
        setLastVerificationResult(verificationResult);
        setActionMessage("Manual restart action completed with live action and verification results.");
      } else if (actionKey === "baseline-reset") {
        const actionResult = await triggerAction({
          action: "baseline-reset",
          namespace: "smartops-dev",
          name: "smartops-erp-simulator",
          dry_run: false,
        });

        const verificationResult = await runVerificationWithRetry({
          namespace: "smartops-dev",
          deployment: "smartops-erp-simulator",
          expected_replicas: 3,
        });

        setSelectedPp2ScenarioKey("");
        setSelectedWindowId("");
        setLastActionResult(actionResult);
        setLastVerificationResult(verificationResult);
        setActionMessage("Baseline reset completed. Chaos was cleared and the ERP simulator was returned to 3 replicas.");
      }

      await loadDashboardState(false, {
        scenarioKey: "",
        windowId: "",
      });
    } catch (err) {
      setActionError(err.message || "Manual DevOps action failed.");
    } finally {
      setRunningManualAction("");
    }
  };

  const clearScenarioBinding = async () => {
    setActionMessage("");
    setActionError("");
    setSelectedPp2ScenarioKey("");
    setSelectedWindowId("");
    setLastActionResult(null);
    setLastVerificationResult(null);
    await loadDashboardState(false, {
      scenarioKey: "",
      windowId: "",
    });
  };

  const liveSummaryCards = liveDashboardState?.summaryCards ?? dashboardState?.summaryCards ?? [];
  const summaryCards = dashboardState?.summaryCards ?? [];
  const livePipelineStages = liveDashboardState?.pipelineStages ?? [];
  const pipelineStages = dashboardState?.pipelineStages ?? [];
  const anomalies = dashboardState?.signals?.anomalies ?? [];
  const rcas = dashboardState?.signals?.rcas ?? [];
  const latestPolicyDecision = dashboardState?.latestPolicyDecision;
  const latestAnomaly = dashboardState?.latestAnomaly;
  const latestRca = dashboardState?.latestRca;
  const lastAnomalyEvidence = dashboardState?.lastAnomalyEvidence;
  const anomalyHistory = dashboardState?.anomalyHistory ?? [];
  const liveSystemState = liveDashboardState?.systemState ?? dashboardState?.systemState;
  const systemState = dashboardState?.systemState;
  const verification = dashboardState?.verification;
  const isOdoo = selectedSystem === "odoo";
  const connectionLabel = error ? "Disconnected" : "Live API connected";


  const humanizePolicyLabel = (policyName, guardrailReason = "") => {
    const raw = String(policyName || "");
    const guardrail = String(guardrailReason || "").toLowerCase();

    if (!raw) {
      return "Not available";
    }

    if (guardrail.includes("restart cooldown")) {
      return "Restart cooldown guardrail";
    }

    const mapping = {
      "scale_up_on_anomaly_resource_step_1": "Resource anomaly scale-up",
      "restart_on_anomaly_error": "Error anomaly restart",
      "manual_scale": "Manual scale",
      "manual_restart": "Manual restart",
    };

    return mapping[raw] || raw.replace(/_/g, " ");
  };

  const humanizeActionLabel = (actionType, decision, guardrailReason = "") => {
    const raw = String(actionType || "").toLowerCase();
    const normalizedDecision = String(decision || "").toLowerCase();
    const guardrail = String(guardrailReason || "").toLowerCase();

    if (normalizedDecision === "blocked") {
      if (guardrail.includes("restart cooldown")) {
        return "Blocked by cooldown";
      }
      return "Blocked before execution";
    }

    if (raw === "scale") return "Scale";
    if (raw === "restart") return "Restart";
    if (!raw) return "No action";
    return actionType;
  };

  const formatDateTime = (value) => {
    if (!value) return "Not available";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  };

  const getStageToneClass = (status) => {
    const normalized = String(status || "").toLowerCase();
    if (["active", "observed", "available", "passed"].includes(normalized)) return "stage-success";
    if (["decision", "planned", "pending", "waiting"].includes(normalized)) return "stage-warning";
    if (["anomaly", "failed", "blocked", "error"].includes(normalized)) return "stage-error";
    return "stage-neutral";
  };

  const boundScenarioTitle =
    selectedPp2ScenarioKey === "scenario-1"
      ? "Scenario 1 - Resource anomaly triggered safe scale-up"
      : selectedPp2ScenarioKey === "scenario-2"
      ? "Scenario 2 - Error anomaly triggered restart"
      : "Scenario 3 - Guarded self-healing through restart cooldown";

  const currentScenarioEvidence =
    !isOdoo && selectedWindowId
      ? {
          title: boundScenarioTitle,
          summary: `This card shows the exact live run currently bound to the dashboard through window ${selectedWindowId}.`,
          mode: "live-window",
          observed: true,
          observedAt: latestPolicyDecision?.ts_utc || latestPolicyDecision?.ts,
          windowIds: [selectedWindowId],
          service: latestAnomaly?.service || "erp-simulator",
          anomalyType: String(latestAnomaly?.type || "").toUpperCase(),
          policy: humanizePolicyLabel(latestPolicyDecision?.policy, latestPolicyDecision?.guardrail_reason),
          action: humanizeActionLabel(latestPolicyDecision?.action_plan?.type, latestPolicyDecision?.decision, latestPolicyDecision?.guardrail_reason),
          targetReplicas: latestPolicyDecision?.action_plan?.scale?.replicas,
          rcaCause: latestRca?.rankedCauses?.[0]?.cause,
          rcaProbability: latestRca?.rankedCauses?.[0]?.probability,
          guardrail: latestPolicyDecision?.guardrail_reason,
          decision: latestPolicyDecision?.decision,
          verifyRequested: latestPolicyDecision?.action_plan?.verify,
        }
      : null;

  const timelineItems = useMemo(() => {
    const items = [];

    if (latestAnomaly) {
      items.push({
        key: `anomaly-${latestAnomaly.windowId || "latest"}`,
        tone: "error",
        title: "Anomaly detected",
        meta: latestAnomaly.ts || latestAnomaly.ts_utc || "Latest anomaly signal",
        body: `Window ${latestAnomaly.windowId || "-"} | Type ${latestAnomaly.type || "unknown"} | Score ${latestAnomaly.score ?? "-"}`,
      });
    }

    if (latestRca) {
      const topCause = latestRca.rankedCauses?.[0];
      items.push({
        key: `rca-${latestRca.windowId || "latest"}`,
        tone: "warning",
        title: "RCA generated",
        meta: latestRca.ts || latestRca.ts_utc || "Latest RCA signal",
        body: `Window ${latestRca.windowId || "-"} | Top cause ${topCause?.cause || "Unknown cause"} | Confidence ${latestRca.confidence ?? "-"}`,
      });
    }

    if (latestPolicyDecision) {
      items.push({
        key: `policy-${latestPolicyDecision.ts_utc || latestPolicyDecision.ts || "latest"}`,
        tone: "info",
        title: "Policy decision",
        meta: latestPolicyDecision.ts_utc || latestPolicyDecision.ts || "Latest policy decision",
        body: `Policy ${humanizePolicyLabel(latestPolicyDecision.policy, latestPolicyDecision.guardrail_reason)} | Decision ${latestPolicyDecision.decision || "-"} | Action ${humanizeActionLabel((latestPolicyDecision.action_plan || {}).type, latestPolicyDecision.decision, latestPolicyDecision.guardrail_reason)}`,
      });
    }

    if (verification) {
      items.push({
        key: `verification-${verification.status || "latest"}`,
        tone: verification.overall === true ? "success" : verification.overall === false ? "error" : "warning",
        title: "Verification state",
        meta: verification.source || "Verification",
        body: verification.message
          ? verification.message
          : `Status ${verification.status || "unknown"} | Ready ${verification.ready_replicas ?? "-"} / ${verification.desired_replicas ?? "-"}`,
      });
    }

    if (!items.length) {
      items.push({
        key: "timeline-empty",
        tone: "neutral",
        title: "No live evidence yet",
        meta: "Timeline",
        body: "No live timeline events are available for the selected system.",
      });
    }

    return items;
  }, [latestAnomaly, latestPolicyDecision, latestRca, verification]);

  const openExternalLink = (url) => {
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const actionDeployment = lastActionResult?.result?.deployment;
  const actionPayload = actionDeployment?.result;
  const verificationStatusRaw = String(lastVerificationResult?.status || "");
  const verificationStatus = verificationStatusRaw.toUpperCase();
  const verificationReady =
    typeof lastVerificationResult?.ready_replicas !== "undefined" &&
    typeof lastVerificationResult?.desired_replicas !== "undefined"
      ? `${lastVerificationResult.ready_replicas}/${lastVerificationResult.desired_replicas}`
      : "N/A";

  const evidencePolicy = lastAnomalyEvidence?.policy || {};
  const evidenceAction = lastAnomalyEvidence?.action || {};
  const evidenceTarget = evidenceAction?.target || {};
  const evidenceVerification = lastAnomalyEvidence?.verification || {};
  const evidenceRca = lastAnomalyEvidence?.rca || {};
  const evidencePriorityLabel = evidencePolicy.priority_label || "Not available";
  const evidencePriorityScore = evidencePolicy.priority_score ?? "Not available";
  const evidencePolicyRank = evidencePolicy.priority ?? "Not available";
  const evidenceVerificationResult =
    evidenceVerification.overall === true
      ? "Passed"
      : evidenceVerification.overall === false
      ? "Failed"
      : "Pending / Not available";
  const evidenceAffectedService =
    latestRca?.rankedCauses?.[0]?.svc || evidenceRca.svc || "Not available";

  return (
    <div className={`app-shell app-shell--${selectedMode}`}>
      <HoverDock activePage={activePage} onPageChange={setActivePage} />
      <div className="app-shell__inner control-center__content">
        <header className="app-header">
          <div>
            <p className="app-header__eyebrow">SmartOps</p>
            <h1>SmartOps Control Center</h1>
            <p className="app-header__subtitle">
              Multi-page operations shell for Monitor - Detect - Diagnose - Decide - Act - Verify
              across ERP-simulator and Odoo.
            </p>
          </div>

          <div className="app-header__controls">
            <div className="toolbar-row">
              <label className="toolbar-field">
                <span>Mode</span>
                <select
                  value={selectedMode}
                  onChange={(event) => setSelectedMode(event.target.value)}
                >
                  {DASHBOARD_MODES.map((mode) => (
                    <option key={mode.value} value={mode.value}>
                      {mode.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="toolbar-field">
                <span>System</span>
                <select
                  value={selectedSystem}
                  onChange={(event) => {
                    const nextSystem = event.target.value;
                    setSelectedSystem(nextSystem);
                    setActionMessage("");
                    setActionError("");
                    setSelectedWindowId("");
                    setLastActionResult(null);
                    setLastVerificationResult(null);
                    if (nextSystem !== "erp-simulator") {
                      setSelectedPp2ScenarioKey("scenario-1");
                    }
                  }}
                >
                  {DASHBOARD_SYSTEMS.map((system) => (
                    <option key={system.value} value={system.value}>
                      {system.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="app-header__badges">
              <span className="badge">Environment: {DASHBOARD_ENV}</span>
              <span className="badge badge--active">
                Mode: {selectedMode === "demo" ? "Demo" : "Live"}
              </span>
              <span className="badge">
                System: {selectedSystem === "odoo" ? "Odoo" : "ERP-simulator"}
              </span>
              <span className="badge">Connection: {connectionLabel}</span>
              <span className="badge">Refresh: {refreshing ? "Updating..." : "Ready"}</span>
              <span className="badge">Bound window: {selectedWindowId || "Current live state"}</span>
            </div>

            <div className="app-header__actions">
              <button
                className="action-button"
                onClick={() => openExternalLink(EXTERNAL_LINKS.grafana)}
                disabled={!EXTERNAL_LINKS.grafana}
              >
                Open Grafana
              </button>
              <button
                className="action-button"
                onClick={() => openExternalLink(EXTERNAL_LINKS.prometheus)}
                disabled={!EXTERNAL_LINKS.prometheus}
              >
                Open Prometheus
              </button>
                <button
                  className="action-button"
                  onClick={() => openExternalLink(EXTERNAL_LINKS.odoo)}
                  disabled={!EXTERNAL_LINKS.odoo}
                >
                  Open Odoo
                </button>
              <button
                className="action-button"
                onClick={clearScenarioBinding}
                disabled={isOdoo || !selectedWindowId}
              >
                Return to current live state
              </button>
              <button
                className="action-button action-button--primary"
                onClick={() => loadDashboardState(false)}
              >
                Refresh
              </button>
            </div>
          </div>
        </header>

        {error ? (
          <section className="panel panel--warning">
            <h2>Live API unavailable</h2>
            <p>{error}</p>
          </section>
        ) : null}

        {actionMessage ? (
          <section className="panel panel--success">
            <h2>Execution update</h2>
            <p>{actionMessage}</p>
            {actionDeployment ? (
              <p>
                Action: {actionDeployment.status} | Attempts: {actionDeployment.attempts} | Duration:{" "}
                {actionDeployment.duration_seconds?.toFixed?.(3) ?? actionDeployment.duration_seconds}s
              </p>
            ) : null}
            {actionPayload ? (
              <p>
                Target: {actionPayload.namespace}/{actionPayload.name}
                {" | "}
                {typeof actionPayload.replicas !== "undefined"
                  ? `Replicas: ${actionPayload.replicas}`
                  : `Restarted at: ${actionPayload.restarted_at}`}
              </p>
            ) : null}
            {lastVerificationResult ? (
              <p>
                Verification: {verificationStatus || "UNKNOWN"} | Ready: {verificationReady}
              </p>
            ) : null}
            {lastVerificationResult?.message ? <p>{lastVerificationResult.message}</p> : null}
          </section>
        ) : null}

        {actionError ? (
          <section className="panel panel--warning">
            <h2>Execution issue</h2>
            <p>{actionError}</p>
          </section>
        ) : null}

        <main className="app-main">
          {activePage === "live" ? (
            <LiveDashboard
              loading={loading}
              refreshing={refreshing}
              error={error}
              environment={DASHBOARD_ENV}
              selectedSystem={selectedSystem}
              liveSummaryCards={liveSummaryCards}
              liveSystemState={liveSystemState}
              pipelineStages={livePipelineStages}
              getStageToneClass={getStageToneClass}
              formatDateTime={formatDateTime}
            />
          ) : activePage === "demo" ? (
            <DemoDashboard
              loading={loading}
              selectedSystem={selectedSystem}
              selectedWindowId={selectedWindowId}
              selectedPp2ScenarioKey={selectedPp2ScenarioKey}
              latestPolicyDecision={latestPolicyDecision}
              latestAnomaly={latestAnomaly}
              latestRca={latestRca}
              verification={verification}
              lastAnomalyEvidence={lastAnomalyEvidence}
              evidencePriorityLabel={evidencePriorityLabel}
              evidencePriorityScore={evidencePriorityScore}
              evidencePolicyRank={evidencePolicyRank}
              evidenceRca={evidenceRca}
              evidenceAffectedService={evidenceAffectedService}
              evidencePolicy={evidencePolicy}
              evidenceAction={evidenceAction}
              evidenceTarget={evidenceTarget}
              evidenceVerification={evidenceVerification}
              evidenceVerificationResult={evidenceVerificationResult}
              anomalyHistory={anomalyHistory}
              pipelineStages={pipelineStages}
              currentScenarioEvidence={currentScenarioEvidence}
              isOdoo={isOdoo}
              runningScenario={runningScenario}
              runningManualAction={runningManualAction}
              runLiveScenario={runLiveScenario}
              runManualDevopsAction={runManualDevopsAction}
              clearScenarioBinding={clearScenarioBinding}
              refreshDashboard={() => loadDashboardState(false)}
              formatDateTime={formatDateTime}
              humanizePolicyLabel={humanizePolicyLabel}
              humanizeActionLabel={humanizeActionLabel}
              getStageToneClass={getStageToneClass}
            />
          ) : activePage === "policy" ? (
            <PolicyStudio
              latestPolicyDecision={latestPolicyDecision}
              currentScenarioEvidence={currentScenarioEvidence}
              formatDateTime={formatDateTime}
              humanizePolicyLabel={humanizePolicyLabel}
              humanizeActionLabel={humanizeActionLabel}
            />
          ) : activePage === "evidence" ? (
            <EvidenceTimeline
              anomalies={anomalies}
              rcas={rcas}
              latestPolicyDecision={latestPolicyDecision}
              latestAnomaly={latestAnomaly}
              latestRca={latestRca}
              verification={verification}
              lastAnomalyEvidence={lastAnomalyEvidence}
              anomalyHistory={anomalyHistory}
              currentScenarioEvidence={currentScenarioEvidence}
              selectedWindowId={selectedWindowId}
              selectedPp2ScenarioKey={selectedPp2ScenarioKey}
              onReviewIncident={(windowId, scenarioKey = selectedPp2ScenarioKey) => {
                if (!windowId) return;
                if (scenarioKey) {
                  setSelectedPp2ScenarioKey(scenarioKey);
                }
                setSelectedWindowId(windowId);
                setActivePage("demo");
              }}
              formatDateTime={formatDateTime}
              humanizePolicyLabel={humanizePolicyLabel}
              humanizeActionLabel={humanizeActionLabel}
            />
          ) : activePage === "integrations" ? (
            <Integrations
              externalLinks={EXTERNAL_LINKS}
              anomaliesCount={anomalies.length}
              rcasCount={rcas.length}
            />
          ) : (
            <Settings />
          )}
          {false ? (
            <>
          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="section-heading__eyebrow">Section A</p>
                <h2>Live system summary</h2>
              </div>
              {liveSystemState ? (
                <div className="section-heading__meta">
                  <span>{liveSystemState.deployment}</span>
                  <span>{liveSystemState.namespace}</span>
                  <span>Live source: current cluster state</span>
                </div>
              ) : null}
            </div>

            {loading ? (
              <div className="empty-state">
                <h3>Loading summary</h3>
                <p>Fetching current SmartOps state.</p>
              </div>
            ) : liveSummaryCards.length === 0 ? (
              <div className="empty-state">
                <h3>No summary data</h3>
                <p>No live summary data is available for the selected system.</p>
              </div>
            ) : (
              <div className="summary-grid">
                {liveSummaryCards.map((card) => (
                  <article key={card.label} className="summary-card">
                    <p className="summary-card__label">{card.label}</p>
                    <p className={`summary-card__value tone-${card.tone}`}>{card.value}</p>
                  </article>
                ))}
              </div>
            )}
          </section>

          {selectedWindowId ? (
            <section className="panel">
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
                <h3>
                  Reviewing {selectedPp2ScenarioKey || "selected scenario"} evidence
                </h3>
                <p>
                  The live system summary above shows the current Kubernetes state.
                  The evidence below is intentionally preserved for the selected incident window,
                  including anomaly detection, RCA, policy decision, remediation action, and verification.
                </p>
              </div>
            </section>
          ) : null}

          <section className="panel">
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
                  Once an anomaly is detected, SmartOps will preserve the last anomaly here
                  even after the live system returns to normal.
                </p>
              </div>
            ) : (
              <div className="scenario-grid">
                <article className="scenario-card">
                  <h3>
                    {String(lastAnomalyEvidence.type || "Unknown").toUpperCase()} anomaly on{" "}
                    {lastAnomalyEvidence.service || "unknown service"}
                  </h3>

                  <div className="pipeline-card__meta">
                    <span className="badge badge--active">
                      Policy Priority: {evidencePriorityLabel}
                    </span>
                    <span>Priority Matrix Score: {evidencePriorityScore}</span>
                    <span>Policy Rank: {evidencePolicyRank}</span>
                  </div>

                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Event ID</span>
                      <span className="detail-row__value">
                        {lastAnomalyEvidence.eventId || "Not available"}
                      </span>
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

                  <h4>Root Cause Analysis</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Top cause</span>
                      <span className="detail-row__value">
                        {evidenceRca.topCause || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Confidence</span>
                      <span className="detail-row__value">
                        {evidenceRca.confidence ?? "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Probability</span>
                      <span className="detail-row__value">
                        {evidenceRca.probability ?? "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Affected service</span>
                      <span className="detail-row__value">{evidenceAffectedService}</span>
                    </div>
                  </div>

                  <h4>Policy Decision and Priority Matrix</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Decision</span>
                      <span className="detail-row__value">
                        {evidencePolicy.decision || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Policy</span>
                      <span className="detail-row__value">
                        {humanizePolicyLabel(evidencePolicy.policy, evidencePolicy.guardrail)}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Guardrail</span>
                      <span className="detail-row__value">
                        {evidencePolicy.guardrail || "allowed"}
                      </span>
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
                      <span className="detail-row__value">
                        {evidencePolicy.execution_mode || "Not available"}
                      </span>
                    </div>
                  </div>

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
                        {evidenceTarget.namespace || "Not available"}/
                        {evidenceTarget.name || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Target kind</span>
                      <span className="detail-row__value">
                        {evidenceTarget.kind || "Deployment"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Target replicas</span>
                      <span className="detail-row__value">
                        {evidenceAction.scale?.replicas ?? "Not applicable"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Dry run / Verify</span>
                      <span className="detail-row__value">
                        {String(evidenceAction.dry_run ?? false)} / {String(evidenceAction.verify ?? false)}
                      </span>
                    </div>
                  </div>

                  <h4>Verification Result</h4>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-row__label">Status</span>
                      <span className="detail-row__value">
                        {evidenceVerification.status || "Not available"}
                      </span>
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
                      <span className="detail-row__value">
                        {evidenceVerification.source || "Not available"}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-row__label">Message</span>
                      <span className="detail-row__value">
                        {evidenceVerification.message || "No verification message available"}
                      </span>
                    </div>
                  </div>

                  <p>
                    Explanation: This evidence is intentionally retained for audit,
                    troubleshooting, and viva demonstration even after the live system
                    has already recovered.
                  </p>
                </article>

                <article className="scenario-card scenario-card--muted">
                  <h3>Recent anomaly history</h3>
                  {anomalyHistory.length === 0 ? (
                    <p>No history records available.</p>
                  ) : (
                    anomalyHistory.slice(0, 5).map((event) => (
                      <p key={event.eventId || event.timestamp}>
                        {formatDateTime(event.ts_utc || event.timestamp)} —{" "}
                        {String(event.type || "unknown").toUpperCase()} /{" "}
                        {event.severity || "unknown"} / {event.service || "unknown"}
                      </p>
                    ))
                  )}
                </article>
              </div>
            )}
          </section>

          <section className="panel">
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
                      <span className="pipeline-card__index">
                        {String(index + 1).padStart(2, "0")}
                      </span>
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
                          <div
                            key={`${stage.key}-${detail.label}-${detailIndex}`}
                            className="detail-row"
                          >
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

          <section className="dashboard-two-column">
            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="section-heading__eyebrow">Section C1</p>
                  <h2>Bound live scenario evidence</h2>
                </div>
              </div>

              {isOdoo ? (
                <div className="empty-state">
                  <h3>PP2 ERP scenarios are hidden for Odoo</h3>
                  <p>These evidence-backed scenarios apply only to the ERP-simulator evaluation flow.</p>
                </div>
              ) : !currentScenarioEvidence ? (
                <div className="empty-state">
                  <h3>No bound live scenario yet</h3>
                    <p>
                      Run Scenario 1, Scenario 2, or Scenario 3 from Section C2. The whole dashboard
                      will then bind to that exact live window.
                    </p>
                </div>
              ) : (
                <div className="scenario-grid">
                  <article className="scenario-card">
                    <h3>{currentScenarioEvidence.title}</h3>
                    <p>{currentScenarioEvidence.summary}</p>
                    <p>
                      Evidence mode: {currentScenarioEvidence.mode} | Observed:{" "}
                      {currentScenarioEvidence.observed ? "Yes" : "No"}
                    </p>
                    <p>
                      Observed at: {formatDateTime(currentScenarioEvidence.observedAt)}
                    </p>
                    <p>
                      Window IDs: {currentScenarioEvidence.windowIds.join(", ")}
                    </p>
                    <p>Service: {currentScenarioEvidence.service}</p>
                      <p>
                        Anomaly: {currentScenarioEvidence.anomalyType || "Not available"} | Policy:{" "}
                        {currentScenarioEvidence.policy || "Not available"} | Action:{" "}
                        {currentScenarioEvidence.action || "Blocked before execution"}
                      </p>
                    {typeof currentScenarioEvidence.targetReplicas !== "undefined" &&
                    currentScenarioEvidence.targetReplicas !== null ? (
                      <p>Target replicas: {currentScenarioEvidence.targetReplicas}</p>
                    ) : null}
                    {currentScenarioEvidence.rcaCause ? (
                      <p>
                        RCA: {currentScenarioEvidence.rcaCause} | Probability:{" "}
                        {currentScenarioEvidence.rcaProbability ?? "Not available"}
                      </p>
                    ) : null}
                    {currentScenarioEvidence.guardrail ? (
                      <p>Guardrail: {currentScenarioEvidence.guardrail}</p>
                    ) : null}
                    <p>
                      Decision: {currentScenarioEvidence.decision || "Not available"} | Verify:{" "}
                      {typeof currentScenarioEvidence.verifyRequested === "boolean"
                        ? currentScenarioEvidence.verifyRequested
                          ? "Requested"
                          : "Not requested"
                        : currentScenarioEvidence.decision === "blocked"
                        ? "Not required"
                        : "Not available"}
                    </p>
                  </article>
                </div>
              )}
            </section>

            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="section-heading__eyebrow">Section C2</p>
                  <h2>Scenario controls</h2>
                </div>
              </div>

              {isOdoo ? (
                <div className="empty-state">
                  <h3>Scenario execution is hidden for Odoo</h3>
                  <p>Live PP2 scenario execution is intentionally limited to ERP-simulator.</p>
                </div>
              ) : (
                <>
                  <div className="scenario-grid">
                    <article className="scenario-card">
                      <h3>Live scenario execution</h3>
                      <p>Use these to run the full PP2 anomaly-to-action flow and bind the dashboard to that exact live window.</p>
                      <div className="scenario-actions">
                        <button
                          className="action-button action-button--primary"
                          onClick={() => runLiveScenario("scenario-1")}
                          disabled={runningScenario === "scenario-1"}
                        >
                          {runningScenario === "scenario-1"
                            ? "Running Scenario 1..."
                            : "Run Scenario 1 / Resource anomaly to scale"}
                        </button>
                        <button
                          className="action-button action-button--primary"
                          onClick={() => runLiveScenario("scenario-2")}
                          disabled={runningScenario === "scenario-2"}
                        >
                          {runningScenario === "scenario-2"
                            ? "Running Scenario 2..."
                            : "Run Scenario 2 / Error anomaly to restart"}
                        </button>
                        <button
                          className="action-button action-button--primary"
                          onClick={() => runLiveScenario("scenario-3")}
                          disabled={runningScenario === "scenario-3"}
                        >
                          {runningScenario === "scenario-3"
                            ? "Running Scenario 3..."
                            : "Run Scenario 3 / Error anomaly to cooldown block"}
                        </button>
                      </div>
                    </article>

                    <article className="scenario-card">
                      <h3>Manual DevOps controls</h3>
                      <p>Use these for direct operational actions without running the full anomaly scenario path.</p>
                      <div className="scenario-actions">
                        <button
                          className="action-button"
                          onClick={() => runManualDevopsAction("manual-scale")}
                          disabled={runningManualAction === "manual-scale"}
                        >
                          {runningManualAction === "manual-scale"
                            ? "Running manual scale..."
                            : "Manual Scale to 4"}
                        </button>
                        <button
                          className="action-button"
                          onClick={() => runManualDevopsAction("manual-restart")}
                          disabled={runningManualAction === "manual-restart"}
                        >
                          {runningManualAction === "manual-restart"
                            ? "Running manual restart..."
                            : "Manual Restart"}
                        </button>
                        <button
                          className="action-button"
                          onClick={() => runManualDevopsAction("baseline-reset")}
                          disabled={runningManualAction === "baseline-reset"}
                        >
                          {runningManualAction === "baseline-reset"
                            ? "Returning to baseline..."
                            : "Return to baseline (3 replicas + clear chaos)"}
                        </button>
                      </div>
                    </article>

                    <article className="scenario-card scenario-card--muted">
                      <h3>Scenario 3</h3>
                      <p>
                        Runs two consecutive error-triggered restart attempts. The first restart is allowed,
                        and the repeated restart should be blocked by cooldown guardrails.
                      </p>
                    </article>
                  </div>
                </>
              )}
            </section>
          </section>

          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="section-heading__eyebrow">Section D</p>
                <h2>External observability</h2>
              </div>
            </div>

            <div className="tool-grid">
              <article className="tool-card">
                <h3>Grafana</h3>
                <p>{EXTERNAL_LINKS.grafana || "Not configured yet."}</p>
              </article>
              <article className="tool-card">
                <h3>Prometheus</h3>
                <p>{EXTERNAL_LINKS.prometheus || "Not configured yet."}</p>
              </article>
              <article className="tool-card">
                <h3>Odoo</h3>
                <p>{EXTERNAL_LINKS.odoo}</p>
              </article>
              <article className="tool-card">
                <h3>Live counts</h3>
                <p>Anomalies: {anomalies.length} | RCA: {rcas.length}</p>
              </article>
            </div>
          </section>

          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="section-heading__eyebrow">Section E</p>
                <h2>Evidence timeline</h2>
              </div>
            </div>

            <div className="timeline-list">
              {timelineItems.map((item) => (
                <article key={item.key} className={`timeline-item timeline-item--${item.tone}`}>
                  <span className="timeline-item__dot" />
                  <div className="timeline-item__content">
                    <div className="timeline-item__header">
                      <h3>{item.title}</h3>
                      <span>{item.meta}</span>
                    </div>
                    <p>{item.body}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default App;
