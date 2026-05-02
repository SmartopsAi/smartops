import { useEffect, useMemo, useState } from "react";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import { getPolicies, getPolicyDecisions } from "../lib/api";

const FALLBACK_POLICIES = [
  {
    name: "scale_up_on_anomaly_resource_step_1",
    trigger: "RESOURCE anomaly",
    action: "Scale ERP simulator to 4 replicas",
    guardrail: "Priority matrix and verification required",
  },
  {
    name: "scale_up_on_anomaly_resource_step_2",
    trigger: "Escalated RESOURCE anomaly",
    action: "Scale up when first remediation is insufficient",
    guardrail: "Bounded scale target and verification required",
  },
  {
    name: "restart_on_anomaly_error",
    trigger: "ERROR anomaly",
    action: "Restart ERP simulator deployment",
    guardrail: "Restart cooldown applies",
  },
  {
    name: "restart cooldown guardrail",
    trigger: "Repeated restart request",
    action: "Block repeated disruptive restart",
    guardrail: "Cooldown window prevents repeated restart",
  },
];

const DSL_PREVIEW = `policy "scale_up_on_anomaly_resource_step_1" {
  when anomaly.type == "RESOURCE" and priority.label in ["P1", "P2"]
  then action.scale deployment "smartops-erp-simulator" replicas 4
  verify deployment_ready
}

policy "restart_on_anomaly_error" {
  when anomaly.type == "ERROR" and rca.confidence >= 0.8
  then action.restart deployment "smartops-erp-simulator"
  verify deployment_ready
}

guardrail "restart cooldown" {
  when action.type == "restart"
  block if previous_restart.within_seconds < 900
}`;

const normalizeList = (payload, keys) => {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
};

const display = (value, fallback = "Not available") =>
  value === null || typeof value === "undefined" || value === "" ? fallback : value;

function PolicyStudio({
  latestPolicyDecision,
  currentScenarioEvidence,
  formatDateTime,
  humanizePolicyLabel,
  humanizeActionLabel,
}) {
  const [policies, setPolicies] = useState([]);
  const [policyError, setPolicyError] = useState("");
  const [policiesLoading, setPoliciesLoading] = useState(true);
  const [decisions, setDecisions] = useState([]);
  const [decisionsError, setDecisionsError] = useState("");
  const [decisionsLoading, setDecisionsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const loadPolicies = async () => {
      try {
        setPoliciesLoading(true);
        const payload = await getPolicies();
        if (!cancelled) {
          setPolicies(normalizeList(payload, ["policies", "items", "results"]));
          setPolicyError("");
        }
      } catch (err) {
        if (!cancelled) {
          setPolicies([]);
          setPolicyError(err.message || "Policy API unavailable.");
        }
      } finally {
        if (!cancelled) setPoliciesLoading(false);
      }
    };

    const loadDecisions = async () => {
      try {
        setDecisionsLoading(true);
        const payload = await getPolicyDecisions(8);
        if (!cancelled) {
          setDecisions(normalizeList(payload, ["decisions", "items", "results"]));
          setDecisionsError("");
        }
      } catch (err) {
        if (!cancelled) {
          setDecisions([]);
          setDecisionsError(err.message || "Policy decisions API unavailable.");
        }
      } finally {
        if (!cancelled) setDecisionsLoading(false);
      }
    };

    loadPolicies();
    loadDecisions();

    return () => {
      cancelled = true;
    };
  }, []);

  const policyCards = useMemo(() => {
    const apiPolicies = policies.map((policy) => ({
      name: policy.name || policy.policy || policy.id || "Unnamed policy",
      trigger: policy.trigger || policy.anomaly_type || policy.anomalyType || "Not available",
      action: policy.action || policy.action_type || policy.actionType || "Not available",
      guardrail: policy.guardrail || policy.guardrail_reason || "Not available",
      priorityLabel: policy.priority_label || policy.priorityLabel || policy.priority || "Not available",
      priorityScore: policy.priority_score ?? policy.priorityScore ?? "Not available",
      lastMatched: policy.last_matched || policy.lastMatched || policy.updated_at || "",
      source: "Policy API",
    }));

    if (apiPolicies.length) return apiPolicies;

    return FALLBACK_POLICIES.map((policy) => ({
      ...policy,
      priorityLabel: latestPolicyDecision?.priority_label || "Not available",
      priorityScore: latestPolicyDecision?.priority_score ?? "Not available",
      lastMatched:
        latestPolicyDecision?.policy && policy.name.includes(String(latestPolicyDecision.policy))
          ? latestPolicyDecision.ts_utc || latestPolicyDecision.ts
          : "",
      source: "Known SmartOps fallback preview",
    }));
  }, [policies, latestPolicyDecision]);

  const recentDecisions = decisions.length ? decisions : latestPolicyDecision ? [latestPolicyDecision] : [];
  const latestActionPlan = latestPolicyDecision?.action_plan || {};
  const latestPriorityAvailable = Boolean(
    latestPolicyDecision?.priority_label ||
      latestPolicyDecision?.priority_score ||
      latestPolicyDecision?.priority ||
      latestPolicyDecision?.decision
  );

  return (
    <div className="policy-studio">
      <PageHeader
        eyebrow="Policy"
        title="Policy Studio"
        description="Review DSL policies, priority matrix outcomes, unmatched anomalies, and AI-assisted policy drafts."
        meta={
          <>
            <span>Mode: Policy preview</span>
            <span>Priority Matrix: Enabled</span>
            <span>CRUD: Coming soon</span>
            <span>AI Drafting: Human approval required</span>
          </>
        }
      />

      <section className="panel policy-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Current DSL Policies</p>
            <h2>Read-only policy catalog</h2>
          </div>
          <div className="section-heading__meta">
            <span>{policiesLoading ? "Loading policies" : policyCards.length ? "Policies available" : "Preview fallback"}</span>
          </div>
        </div>

        {policyError ? (
          <div className="empty-state policy-inline-state">
            <h3>Policy API unavailable</h3>
            <p>{policyError}. Showing known SmartOps policy previews instead.</p>
          </div>
        ) : null}

        <div className="policy-card-grid">
          {policyCards.map((policy) => (
            <article key={policy.name} className="policy-card">
              <div className="policy-card__top">
                <h3>{policy.name}</h3>
                <span className="service-card__status service-card__status--configured">Read-only preview</span>
              </div>
              <div className="policy-detail-grid">
                <div>
                  <span>Trigger / anomaly type</span>
                  <strong>{display(policy.trigger)}</strong>
                </div>
                <div>
                  <span>Expected action</span>
                  <strong>{display(policy.action)}</strong>
                </div>
                <div>
                  <span>Guardrail behavior</span>
                  <strong>{display(policy.guardrail)}</strong>
                </div>
                <div>
                  <span>Priority</span>
                  <strong>
                    {display(policy.priorityLabel)} / {display(policy.priorityScore)}
                  </strong>
                </div>
                <div>
                  <span>Last matched</span>
                  <strong>{policy.lastMatched ? formatDateTime(policy.lastMatched) : "Not available"}</strong>
                </div>
                <div>
                  <span>Source</span>
                  <strong>{policy.source}</strong>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="policy-studio__split">
        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Policy Editor Preview</p>
              <h2>Read-only DSL preview</h2>
            </div>
          </div>

          <pre className="policy-code-preview">
            <code>{DSL_PREVIEW}</code>
          </pre>

          <div className="policy-editor-actions">
            {["Validate DSL", "Save Policy", "Delete Policy", "Deploy Policy"].map((label) => (
              <button key={label} className="action-button" type="button" disabled>
                {label} - Coming soon
              </button>
            ))}
          </div>
        </section>

        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Priority Matrix</p>
              <h2>Decision priority outcome</h2>
            </div>
          </div>

          <div className="priority-level-list">
            <article>
              <strong>P1</strong>
              <span>Critical service impact with high confidence</span>
            </article>
            <article>
              <strong>P2</strong>
              <span>Important but lower urgency</span>
            </article>
            <article>
              <strong>P3</strong>
              <span>Low urgency / monitor</span>
            </article>
          </div>

          {latestPriorityAvailable ? (
            <div className="policy-detail-grid policy-detail-grid--single">
              <div>
                <span>Latest priority label</span>
                <strong>{display(latestPolicyDecision?.priority_label)}</strong>
              </div>
              <div>
                <span>Latest priority score</span>
                <strong>{display(latestPolicyDecision?.priority_score)}</strong>
              </div>
              <div>
                <span>Policy rank / priority</span>
                <strong>{display(latestPolicyDecision?.priority)}</strong>
              </div>
              <div>
                <span>Guardrail reason</span>
                <strong>{display(latestPolicyDecision?.guardrail_reason, "Not applicable")}</strong>
              </div>
              <div>
                <span>Decision</span>
                <strong>{display(latestPolicyDecision?.decision)}</strong>
              </div>
              <div>
                <span>Policy</span>
                <strong>{humanizePolicyLabel(latestPolicyDecision?.policy, latestPolicyDecision?.guardrail_reason)}</strong>
              </div>
            </div>
          ) : (
            <EmptyState title="No recent priority decision">
              Run a Demo Lab scenario or wait for a live policy decision to populate this panel.
            </EmptyState>
          )}
        </section>
      </section>

      <section className="policy-studio__split">
        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Unmatched Anomalies</p>
              <h2>Unmatched anomalies</h2>
            </div>
          </div>

          <EmptyState title="No unmatched anomaly API is connected yet.">
            When an anomaly has no matching DSL policy, it will appear here for operator review.
            The operator can then draft a new DSL policy, validate it, and deploy it after human approval.
          </EmptyState>

          <article className="policy-example-card">
            <span className="badge">Example only - preview</span>
            <h3>Unknown anomaly pattern</h3>
            <p>Type: network_latency</p>
            <p>Service: erp-simulator</p>
            <p>RCA: External dependency timeout</p>
            <p>Suggested response: Draft policy for review</p>
          </article>
        </section>

        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">AI Draft Assistant</p>
              <h2>AI Policy Draft Assistant</h2>
            </div>
          </div>

          <div className="ai-draft-layout">
            <article className="policy-example-card">
              <h3>Anomaly summary preview</h3>
              <p>
                {currentScenarioEvidence
                  ? `${currentScenarioEvidence.anomalyType || "Unknown"} anomaly on ${currentScenarioEvidence.service || "unknown service"}`
                  : "Select or run an incident to preview anomaly context here."}
              </p>
            </article>
            <pre className="policy-code-preview policy-code-preview--compact">
              <code>{`draft policy "operator_review_required" {
  when anomaly.pattern == "unmatched"
  then suggest action.review
  require human_approval
}`}</code>
            </pre>
            <div className="policy-editor-actions">
              <button className="action-button" type="button" disabled>
                Generate policy draft - Coming soon
              </button>
              <button className="action-button" type="button" disabled>
                Validate generated DSL - Coming soon
              </button>
              <button className="action-button" type="button" disabled>
                Save after review - Coming soon
              </button>
            </div>
            <div className="policy-safety-notes">
              <p>AI drafts require human approval.</p>
              <p>DSL must be validated before deployment.</p>
              <p>Guardrails and priority matrix still apply.</p>
              <p>Never store secrets or credentials in frontend code.</p>
            </div>
          </div>
        </section>
      </section>

      <section className="panel policy-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Recent Decisions</p>
            <h2>Recent policy decisions</h2>
          </div>
          <div className="section-heading__meta">
            <span>{decisionsLoading ? "Loading decisions" : decisionsError ? "Fallback context" : "Policy decisions API"}</span>
          </div>
        </div>

        {decisionsError && !recentDecisions.length ? (
          <EmptyState title="Recent policy decisions unavailable">
            {decisionsError}. Run a scenario to populate the latest decision context.
          </EmptyState>
        ) : (
          <div className="policy-decision-list">
            {recentDecisions.map((decision, index) => {
              const actionPlan = decision.action_plan || {};
              return (
                <article key={`${decision.ts_utc || decision.ts || "decision"}-${index}`} className="policy-decision-row">
                  <span>{formatDateTime(decision.ts_utc || decision.ts)}</span>
                  <span>{humanizePolicyLabel(decision.policy, decision.guardrail_reason)}</span>
                  <span>{display(decision.decision)}</span>
                  <span>{display(decision.guardrail_reason, "Not applicable")}</span>
                  <span>{display(decision.priority_label || decision.priority)}</span>
                  <span>{humanizeActionLabel(actionPlan.type, decision.decision, decision.guardrail_reason)}</span>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

export default PolicyStudio;
