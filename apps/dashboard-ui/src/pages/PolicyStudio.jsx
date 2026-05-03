import { useCallback, useEffect, useMemo, useState } from "react";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import {
  createPolicyDefinition,
  deletePolicyDefinition,
  disablePolicyDefinition,
  enablePolicyDefinition,
  generatePolicyDraft,
  getPolicyChangeAudit,
  getPolicyDefinitions,
  getUnmatchedAnomalies,
  reloadPolicies,
  updatePolicyDefinition,
  updateUnmatchedAnomalyStatus,
  validatePolicyDsl,
  verifyAdminKey,
} from "../lib/api";

const DEFAULT_DSL = `POLICY "operator_review_draft":
  WHEN anomaly.type == "error"
       AND anomaly.score >= 0.9
  THEN restart(service)
  PRIORITY 200`;

const display = (value, fallback = "Not available") =>
  value === null || typeof value === "undefined" || value === "" ? fallback : value;

const normalizeList = (payload, keys) => {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
};

const getPolicyId = (policy) => policy?.id || policy?.policy_id || policy?.name || "";

const getPolicyStatus = (policy) => {
  if (policy?.deleted) return "deleted";
  if (policy?.status) return String(policy.status).toLowerCase();
  if (policy?.enabled) return "active";
  return "draft";
};

const statusClass = (status) => `policy-badge policy-badge--${String(status || "draft").toLowerCase()}`;

const getParsedActionType = (policy) => {
  const action = policy?.parsed?.action || policy?.action || {};
  if (typeof action === "string") return action;
  return action.type || action.action_type || action.name || "Not available";
};

const getParsedPriority = (policy) =>
  policy?.parsed?.priority ?? policy?.priority ?? policy?.priority_score ?? "Not available";

const extractDraftName = (draft) => {
  const parsedName = draft?.validation?.parsed?.policies?.[0]?.name || draft?.parsed?.policies?.[0]?.name;
  if (parsedName) return parsedName;
  const match = String(draft?.draft_dsl || "").match(/POLICY\s+"([^"]+)"/i);
  return match?.[1] || "ai_generated_policy_draft";
};

const getUnmatchedId = (anomaly) => anomaly?.id || "";

function PolicyStudio({
  latestPolicyDecision,
  currentScenarioEvidence,
  formatDateTime,
  humanizePolicyLabel,
  humanizeActionLabel,
}) {
  const [adminKey, setAdminKey] = useState("");
  const [adminVerified, setAdminVerified] = useState(false);
  const [adminError, setAdminError] = useState("");

  const [policyDefinitions, setPolicyDefinitions] = useState([]);
  const [policiesLoading, setPoliciesLoading] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [selectedPolicyId, setSelectedPolicyId] = useState("");

  const [editorName, setEditorName] = useState("operator_review_draft");
  const [editorDsl, setEditorDsl] = useState(DEFAULT_DSL);
  const [editorReason, setEditorReason] = useState("");

  const [validationResult, setValidationResult] = useState(null);
  const [validationLoading, setValidationLoading] = useState(false);

  const [unmatchedAnomalies, setUnmatchedAnomalies] = useState([]);
  const [unmatchedLoading, setUnmatchedLoading] = useState(true);
  const [unmatchedError, setUnmatchedError] = useState("");
  const [selectedUnmatchedId, setSelectedUnmatchedId] = useState("");

  const [aiDraft, setAiDraft] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");

  const [changeAudit, setChangeAudit] = useState([]);
  const [auditLoading, setAuditLoading] = useState(true);
  const [auditError, setAuditError] = useState("");

  const [actionBusy, setActionBusy] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");

  const activeCount = useMemo(
    () =>
      policyDefinitions.filter(
        (policy) => policy.enabled === true && !policy.deleted && getPolicyStatus(policy) === "active"
      ).length,
    [policyDefinitions]
  );

  const selectedPolicy = useMemo(
    () => policyDefinitions.find((policy) => getPolicyId(policy) === selectedPolicyId) || null,
    [policyDefinitions, selectedPolicyId]
  );

  const visibleAudit = useMemo(() => changeAudit.slice(0, 12), [changeAudit]);
  const selectedUnmatchedAnomaly = useMemo(
    () => unmatchedAnomalies.find((anomaly) => getUnmatchedId(anomaly) === selectedUnmatchedId) || null,
    [selectedUnmatchedId, unmatchedAnomalies]
  );

  const selectPolicy = useCallback((policy) => {
    const id = getPolicyId(policy);
    setSelectedPolicyId(id);
    setEditorName(policy?.name || policy?.id || "");
    setEditorDsl(policy?.dsl || DEFAULT_DSL);
    setValidationResult(policy?.validation || null);
    setActionMessage("");
    setActionError("");
  }, []);

  const loadPolicyDefinitions = useCallback(async () => {
    try {
      setPoliciesLoading(true);
      const payload = await getPolicyDefinitions();
      const definitions = normalizeList(payload, ["policies", "items", "results", "definitions"]);
      setPolicyDefinitions(definitions);
      setPolicyError("");
      setSelectedPolicyId((currentId) => {
        if (currentId && definitions.some((policy) => getPolicyId(policy) === currentId)) {
          return currentId;
        }
        const firstAvailable = definitions.find((policy) => !policy.deleted) || definitions[0];
        if (firstAvailable) {
          setEditorName(firstAvailable.name || firstAvailable.id || "");
          setEditorDsl(firstAvailable.dsl || DEFAULT_DSL);
          setValidationResult(firstAvailable.validation || null);
          return getPolicyId(firstAvailable);
        }
        return "";
      });
    } catch (err) {
      setPolicyDefinitions([]);
      setPolicyError(err.message || "Policy definitions API unavailable.");
    } finally {
      setPoliciesLoading(false);
    }
  }, []);

  const loadUnmatchedAnomalies = useCallback(async () => {
    try {
      setUnmatchedLoading(true);
      const payload = await getUnmatchedAnomalies();
      setUnmatchedAnomalies(
        normalizeList(payload, ["unmatched_anomalies", "anomalies", "items", "results", "records"])
      );
      setUnmatchedError("");
    } catch (err) {
      setUnmatchedAnomalies([]);
      setUnmatchedError(err.message || "Unmatched anomaly API unavailable.");
    } finally {
      setUnmatchedLoading(false);
    }
  }, []);

  const loadChangeAudit = useCallback(async () => {
    try {
      setAuditLoading(true);
      const payload = await getPolicyChangeAudit(25);
      const events = normalizeList(payload, ["events", "audit", "items", "results"]);
      setChangeAudit(events.reverse());
      setAuditError("");
    } catch (err) {
      setChangeAudit([]);
      setAuditError(err.message || "Policy change audit unavailable.");
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadPolicyDefinitions(), loadUnmatchedAnomalies(), loadChangeAudit()]);
  }, [loadChangeAudit, loadPolicyDefinitions, loadUnmatchedAnomalies]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const requireAdmin = () => {
    if (!adminKey.trim()) {
      setActionError("Admin API key is required for this action.");
      return false;
    }
    if (!adminVerified) {
      setActionError("Verify the Admin API key before running protected policy actions.");
      return false;
    }
    return true;
  };

  const actionPayload = (fallbackReason = "Policy Studio update") => ({
    updated_by: "operator",
    reason: editorReason || fallbackReason,
  });

  const runProtectedAction = async (label, operation) => {
    if (!requireAdmin()) return;
    try {
      setActionBusy(label);
      setActionError("");
      setActionMessage("");
      await operation();
      setActionMessage(`${label} completed.`);
      await refreshAll();
    } catch (err) {
      setActionError(err.message || `${label} failed.`);
    } finally {
      setActionBusy("");
    }
  };

  const handleVerifyAdmin = async () => {
    if (!adminKey.trim()) {
      setAdminVerified(false);
      setAdminError("Invalid/missing key.");
      return;
    }
    try {
      setAdminError("");
      const payload = await verifyAdminKey(adminKey.trim());
      setAdminVerified(Boolean(payload?.admin || payload?.status === "ok"));
      if (!(payload?.admin || payload?.status === "ok")) {
        setAdminError("Admin verification did not return an approved status.");
      }
    } catch (err) {
      setAdminVerified(false);
      setAdminError(err.message || "Admin verification failed.");
    }
  };

  const handleClearAdmin = () => {
    setAdminKey("");
    setAdminVerified(false);
    setAdminError("");
  };

  const handleValidate = async (dsl = editorDsl) => {
    try {
      setValidationLoading(true);
      setActionError("");
      const result = await validatePolicyDsl({ dsl, mode: "draft" });
      setValidationResult(result);
      setActionMessage(result?.valid ? "DSL validation passed." : "DSL validation failed.");
      return result;
    } catch (err) {
      setValidationResult({
        valid: false,
        errors: [{ field: "dsl", message: err.message || "Validation request failed." }],
        warnings: [],
        parsed: null,
      });
      setActionError(err.message || "Validation request failed.");
      return null;
    } finally {
      setValidationLoading(false);
    }
  };

  const handleCreateDraft = async (dsl = editorDsl, name = editorName, reason = "Policy Studio create draft") => {
    await runProtectedAction("Create Draft", async () => {
      const payload = {
        name,
        dsl,
        updated_by: "operator",
        reason: editorReason || reason,
      };
      const created = await createPolicyDefinition(payload, adminKey.trim());
      const policy = created?.policy;
      if (policy) {
        selectPolicy(policy);
      }
    });
  };

  const handleUpdateSelected = async () => {
    if (!selectedPolicyId) {
      setActionError("Select a policy before updating.");
      return;
    }
    await runProtectedAction("Update Selected", async () => {
      await updatePolicyDefinition(
        selectedPolicyId,
        {
          name: editorName,
          dsl: editorDsl,
          updated_by: "operator",
          reason: editorReason || "Policy Studio update",
        },
        adminKey.trim()
      );
    });
  };

  const handleSoftDelete = async () => {
    if (!selectedPolicyId) {
      setActionError("Select a policy before deleting.");
      return;
    }
    if (!window.confirm("Soft delete this policy? It will be disabled and marked deleted.")) return;
    await runProtectedAction("Soft Delete", async () => {
      await deletePolicyDefinition(selectedPolicyId, actionPayload("Policy Studio soft delete"), adminKey.trim());
    });
  };

  const handleEnable = async () => {
    if (!selectedPolicyId) {
      setActionError("Select a policy before enabling.");
      return;
    }
    if (!window.confirm("Enable this policy for the active policy set?")) return;
    await runProtectedAction("Enable Policy", async () => {
      await enablePolicyDefinition(selectedPolicyId, actionPayload("Policy Studio enable"), adminKey.trim());
    });
  };

  const handleDisable = async () => {
    if (!selectedPolicyId) {
      setActionError("Select a policy before disabling.");
      return;
    }
    await runProtectedAction("Disable Policy", async () => {
      await disablePolicyDefinition(selectedPolicyId, actionPayload("Policy Studio disable"), adminKey.trim());
    });
  };

  const handleReload = async () => {
    if (!window.confirm("Reload the active policy set after validation?")) return;
    await runProtectedAction("Reload Active Set", async () => {
      await reloadPolicies(actionPayload("Policy Studio reload"), adminKey.trim());
    });
  };

  const handleUpdateUnmatchedStatus = async (anomaly, status) => {
    const id = getUnmatchedId(anomaly);
    if (!id) return;
    await runProtectedAction(`Mark ${status}`, async () => {
      await updateUnmatchedAnomalyStatus(
        id,
        {
          status,
          updated_by: "operator",
          reason: "Reviewed in Policy Studio",
        },
        adminKey.trim()
      );
    });
  };

  const handleSelectUnmatched = (anomaly) => {
    const id = getUnmatchedId(anomaly);
    if (!id) {
      setAiError("Selected unmatched anomaly is missing an id.");
      return;
    }
    setSelectedUnmatchedId(id);
    setAiDraft(null);
    setAiError("");
    setActionError("");
  };

  const handleGenerateDraft = async () => {
    if (!adminKey.trim()) {
      setAiError("Admin API key is required to generate an AI draft.");
      return;
    }
    if (!adminVerified) {
      setAiError("Verify the Admin API key before generating an AI draft.");
      return;
    }
    if (!selectedUnmatchedAnomaly?.id) {
      setAiError("Select an unmatched anomaly before generating an AI draft.");
      return;
    }
    try {
      setAiLoading(true);
      setAiError("");
      setActionError("");
      const result = await generatePolicyDraft(
        {
          unmatched_anomaly_id: selectedUnmatchedAnomaly.id,
          constraints: {
            preferred_action: "auto",
            max_replicas: 4,
          },
        },
        adminKey.trim()
      );
      setAiDraft(result);
      setActionMessage("AI draft generated for human review.");
    } catch (err) {
      setAiError(err.message || "AI draft generation failed.");
    } finally {
      setAiLoading(false);
    }
  };

  const copyDraftToEditor = () => {
    if (!aiDraft?.draft_dsl) return;
    setEditorDsl(aiDraft.draft_dsl);
    setEditorName(extractDraftName(aiDraft));
    setValidationResult(aiDraft.validation || null);
    setActionMessage("AI draft copied into editor. Review before saving.");
  };

  const saveDraftAsPolicy = async () => {
    if (!aiDraft?.draft_dsl) return;
    await handleCreateDraft(aiDraft.draft_dsl, extractDraftName(aiDraft), "AI draft saved after human review");
  };

  const latestActionPlan = latestPolicyDecision?.action_plan || {};
  const latestPriorityAvailable = Boolean(
    latestPolicyDecision?.priority_label ||
      latestPolicyDecision?.priority_score ||
      latestPolicyDecision?.priority ||
      latestPolicyDecision?.decision
  );

  const selectedStatus = getPolicyStatus(selectedPolicy);

  return (
    <div className="policy-studio">
      <PageHeader
        eyebrow="Policy"
        title="Policy Studio"
        description="Review, validate, draft, and safely deploy SmartOps DSL policies."
        meta={
          <>
            <span>Mode: Governed</span>
            <span>Admin: {adminVerified ? "Verified" : "Not verified"}</span>
            <span>Policies: {policyDefinitions.length}</span>
            <span>Active: {activeCount}</span>
            <span>Unmatched: {unmatchedAnomalies.length}</span>
          </>
        }
      />

      <section className="panel policy-section policy-admin-panel">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Admin Access</p>
            <h2>Protected policy operations</h2>
          </div>
          <span className={adminVerified ? "policy-badge policy-badge--valid" : "policy-badge policy-badge--invalid"}>
            {adminVerified ? "Verified" : "Not verified"}
          </span>
        </div>

        <div className="policy-admin-panel__form">
          <label>
            <span>Admin API Key</span>
            <input
              type="password"
              value={adminKey}
              onChange={(event) => {
                setAdminKey(event.target.value);
                setAdminVerified(false);
              }}
              placeholder="Enter key for protected actions"
              autoComplete="off"
            />
          </label>
          <div className="policy-action-row">
            <button className="action-button" type="button" onClick={handleVerifyAdmin} disabled={!adminKey.trim()}>
              Verify admin key
            </button>
            <button className="action-button action-button--muted" type="button" onClick={handleClearAdmin}>
              Clear key
            </button>
          </div>
        </div>
        {adminError ? <p className="policy-error-text">{adminError}</p> : null}
        <p className="policy-muted-text">
          The admin key is kept only in React state for this page session. It is never shown after entry and is not stored in localStorage.
        </p>
      </section>

      <section className="policy-studio-grid">
        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Policy Catalog</p>
              <h2>Policy definitions</h2>
            </div>
            <div className="section-heading__meta">
              <span>{policiesLoading ? "Loading" : "Read endpoint"}</span>
            </div>
          </div>

          {policyError ? (
            <EmptyState title="Policy definitions unavailable">{policyError}</EmptyState>
          ) : policyDefinitions.length ? (
            <div className="policy-list">
              {policyDefinitions.map((policy) => {
                const id = getPolicyId(policy);
                const status = getPolicyStatus(policy);
                const selected = id === selectedPolicyId;
                return (
                  <button
                    key={id}
                    className={`policy-list-card${selected ? " policy-list-card--selected" : ""}`}
                    type="button"
                    onClick={() => selectPolicy(policy)}
                  >
                    <div className="policy-list-card__top">
                      <strong>{display(policy.name || id)}</strong>
                      <span className={statusClass(status)}>{status}</span>
                    </div>
                    <div className="policy-list-card__meta">
                      <span>ID: {display(id)}</span>
                      <span>Enabled: {policy.enabled ? "true" : "false"}</span>
                      <span>Version: {display(policy.version, "1")}</span>
                      <span>Action: {getParsedActionType(policy)}</span>
                      <span>Priority: {getParsedPriority(policy)}</span>
                      <span>Source: {display(policy.source)}</span>
                      <span>Updated by: {display(policy.updated_by)}</span>
                      <span>Updated: {policy.updated_at ? formatDateTime(policy.updated_at) : "Not available"}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyState title="No policy definitions found">
              Create a disabled draft policy after validating DSL, or check the policy engine connection.
            </EmptyState>
          )}
        </section>

        <section className="panel policy-section policy-editor">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">DSL Editor</p>
              <h2>{selectedPolicy ? "Selected policy editor" : "Draft editor"}</h2>
            </div>
            {selectedPolicy ? <span className={statusClass(selectedStatus)}>{selectedStatus}</span> : null}
          </div>

          <div className="policy-editor-fields">
            <label>
              <span>Policy name</span>
              <input value={editorName} onChange={(event) => setEditorName(event.target.value)} />
            </label>
            <label>
              <span>Reason for audit log</span>
              <input
                value={editorReason}
                onChange={(event) => setEditorReason(event.target.value)}
                placeholder="Reason for audit log"
              />
            </label>
            <label className="policy-editor-fields__dsl">
              <span>Policy DSL</span>
              <textarea
                className="policy-code-textarea"
                value={editorDsl}
                onChange={(event) => setEditorDsl(event.target.value)}
                spellCheck="false"
              />
            </label>
          </div>

          <div className="policy-action-row policy-action-row--wrap">
            <button className="action-button" type="button" onClick={() => handleValidate()} disabled={validationLoading}>
              {validationLoading ? "Validating..." : "Validate DSL"}
            </button>
            <button className="action-button" type="button" onClick={() => handleCreateDraft()} disabled={!adminVerified || Boolean(actionBusy)}>
              Create Draft
            </button>
            <button className="action-button" type="button" onClick={handleUpdateSelected} disabled={!adminVerified || !selectedPolicyId || Boolean(actionBusy)}>
              Update Selected
            </button>
            <button className="action-button action-button--danger" type="button" onClick={handleSoftDelete} disabled={!adminVerified || !selectedPolicyId || Boolean(actionBusy)}>
              Soft Delete
            </button>
            <button className="action-button" type="button" onClick={handleEnable} disabled={!adminVerified || !selectedPolicyId || Boolean(actionBusy)}>
              Enable
            </button>
            <button className="action-button action-button--muted" type="button" onClick={handleDisable} disabled={!adminVerified || !selectedPolicyId || Boolean(actionBusy)}>
              Disable
            </button>
            <button className="action-button" type="button" onClick={handleReload} disabled={!adminVerified || Boolean(actionBusy)}>
              Reload Active Set
            </button>
            <button className="action-button action-button--muted" type="button" onClick={refreshAll} disabled={Boolean(actionBusy)}>
              Refresh
            </button>
          </div>

          {actionBusy ? <p className="policy-muted-text">Running: {actionBusy}</p> : null}
          {actionMessage ? <p className="policy-success-text">{actionMessage}</p> : null}
          {actionError ? <p className="policy-error-text">{actionError}</p> : null}
        </section>
      </section>

      <section className="policy-studio__split">
        <section className="panel policy-section policy-validation-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Validation</p>
              <h2>DSL validation result</h2>
            </div>
            {validationResult ? (
              <span className={validationResult.valid ? "policy-badge policy-badge--valid" : "policy-badge policy-badge--invalid"}>
                {validationResult.valid ? "Valid" : "Invalid"}
              </span>
            ) : null}
          </div>

          {validationResult ? (
            <div className="policy-validation-content">
              <div className="policy-detail-grid">
                <div>
                  <span>Valid</span>
                  <strong>{validationResult.valid ? "true" : "false"}</strong>
                </div>
                <div>
                  <span>Policy count</span>
                  <strong>{display(validationResult.parsed?.policy_count)}</strong>
                </div>
              </div>

              <div className="policy-message-list">
                <h3>Errors</h3>
                {(validationResult.errors || []).length ? (
                  (validationResult.errors || []).map((error, index) => (
                    <p key={`${error.field || "error"}-${index}`} className="policy-error-text">
                      {error.field ? `${error.field}: ` : ""}
                      {error.message || String(error)}
                    </p>
                  ))
                ) : (
                  <p className="policy-muted-text">No errors.</p>
                )}
              </div>

              <div className="policy-message-list">
                <h3>Warnings</h3>
                {(validationResult.warnings || []).length ? (
                  (validationResult.warnings || []).map((warning, index) => (
                    <p key={`warning-${index}`} className="policy-warning-text">
                      {warning.message || String(warning)}
                    </p>
                  ))
                ) : (
                  <p className="policy-muted-text">No warnings.</p>
                )}
              </div>

              {validationResult.parsed?.policies?.length ? (
                <div className="policy-mini-list">
                  {validationResult.parsed.policies.map((policy, index) => (
                    <article key={`${policy.name || "policy"}-${index}`}>
                      <strong>{display(policy.name)}</strong>
                      <span>Action: {display(policy.action?.type || policy.action_type || policy.action)}</span>
                      <span>Priority: {display(policy.priority)}</span>
                    </article>
                  ))}
                </div>
              ) : null}

              {validationResult.safety ? (
                <div className="policy-safety-grid">
                  {Object.entries(validationResult.safety).map(([key, value]) => (
                    <span key={key} className={value ? "policy-badge policy-badge--valid" : "policy-badge policy-badge--invalid"}>
                      {key}: {String(value)}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyState title="No validation run yet">Validate the editor DSL or generate an AI draft to inspect safety results.</EmptyState>
          )}
        </section>

        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Priority Matrix</p>
              <h2>Latest decision context</h2>
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
                <span>Policy</span>
                <strong>{humanizePolicyLabel(latestPolicyDecision?.policy, latestPolicyDecision?.guardrail_reason)}</strong>
              </div>
              <div>
                <span>Decision</span>
                <strong>{display(latestPolicyDecision?.decision)}</strong>
              </div>
              <div>
                <span>Action</span>
                <strong>
                  {humanizeActionLabel(latestActionPlan.type, latestPolicyDecision?.decision, latestPolicyDecision?.guardrail_reason)}
                </strong>
              </div>
              <div>
                <span>Priority</span>
                <strong>
                  {display(latestPolicyDecision?.priority_label || latestPolicyDecision?.priority)} /{" "}
                  {display(latestPolicyDecision?.priority_score)}
                </strong>
              </div>
            </div>
          ) : (
            <EmptyState title="No recent priority decision">Run a Demo Lab scenario to populate decision context.</EmptyState>
          )}
        </section>
      </section>

      <section className="policy-studio__split">
        <section className="panel policy-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Unmatched Anomalies</p>
              <h2>Policy gaps for review</h2>
            </div>
            <div className="section-heading__meta">
              <span>{unmatchedLoading ? "Loading" : `${unmatchedAnomalies.length} records`}</span>
            </div>
          </div>

          {unmatchedError ? (
            <EmptyState title="Unmatched anomalies unavailable">{unmatchedError}</EmptyState>
          ) : unmatchedAnomalies.length ? (
            <div className="unmatched-anomaly-grid">
              {unmatchedAnomalies.map((anomaly) => (
                <article
                  key={anomaly.id || anomaly.window_id}
                  className={`unmatched-anomaly-card ${
                    selectedUnmatchedId === getUnmatchedId(anomaly) ? "unmatched-anomaly-card--selected" : ""
                  }`}
                >
                  <div className="policy-list-card__top">
                    <strong>{display(anomaly.id || anomaly.window_id)}</strong>
                    <span className={statusClass(anomaly.status || "new")}>{display(anomaly.status, "new")}</span>
                  </div>
                  <div className="policy-detail-grid policy-detail-grid--single">
                    <div>
                      <span>Window / service</span>
                      <strong>
                        {display(anomaly.window_id)} / {display(anomaly.service)}
                      </strong>
                    </div>
                    <div>
                      <span>Type / risk / score</span>
                      <strong>
                        {display(anomaly.anomaly_type)} / {display(anomaly.risk)} / {display(anomaly.score)}
                      </strong>
                    </div>
                    <div>
                      <span>RCA</span>
                      <strong>
                        {display(anomaly.rca_cause)} ({display(anomaly.rca_probability)})
                      </strong>
                    </div>
                    <div>
                      <span>Count / first seen / last seen</span>
                      <strong>
                        {display(anomaly.count)} / {anomaly.first_seen ? formatDateTime(anomaly.first_seen) : "Not available"} /{" "}
                        {anomaly.last_seen ? formatDateTime(anomaly.last_seen) : "Not available"}
                      </strong>
                    </div>
                  </div>
                  <div className="policy-action-row policy-action-row--wrap">
                    <button className="action-button" type="button" onClick={() => handleSelectUnmatched(anomaly)}>
                      {selectedUnmatchedId === getUnmatchedId(anomaly) ? "Selected" : "Select for AI Draft"}
                    </button>
                    <button className="action-button action-button--muted" type="button" onClick={() => handleUpdateUnmatchedStatus(anomaly, "ignored")} disabled={!adminVerified || Boolean(actionBusy)}>
                      Mark Ignored
                    </button>
                    <button className="action-button action-button--muted" type="button" onClick={() => handleUpdateUnmatchedStatus(anomaly, "resolved")} disabled={!adminVerified || Boolean(actionBusy)}>
                      Mark Resolved
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No unmatched anomaly evidence">
              Run a Demo Lab scenario or wait for live anomaly detection to create policy gap records.
            </EmptyState>
          )}
        </section>

        <section className="panel policy-section ai-draft-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">AI Policy Draft Assistant</p>
              <h2>Generate draft DSL from unmatched anomalies</h2>
            </div>
            {aiDraft ? (
              <span className={aiDraft.validation?.valid ? "policy-badge policy-badge--valid" : "policy-badge policy-badge--invalid"}>
                {aiDraft.validation?.valid ? "Valid draft" : "Needs review"}
              </span>
            ) : null}
          </div>

          <div className="policy-safety-notes">
            <p>
              AI drafts are not saved, enabled, reloaded, deployed, or executed automatically.
            </p>
            <p>
              Flow: select an unmatched anomaly, generate a draft, review validation, copy it into the editor, then explicitly save it as a disabled draft.
            </p>
          </div>

          <div className="policy-detail-grid policy-detail-grid--single">
            <div>
              <span>Selected unmatched anomaly</span>
              <strong>
                {selectedUnmatchedAnomaly
                  ? `${display(selectedUnmatchedAnomaly.id)} / window ${display(selectedUnmatchedAnomaly.window_id)}`
                  : "Select an unmatched anomaly from the policy gaps list."}
              </strong>
            </div>
            <div>
              <span>Selected service / type</span>
              <strong>
                {selectedUnmatchedAnomaly
                  ? `${display(selectedUnmatchedAnomaly.service)} / ${display(selectedUnmatchedAnomaly.anomaly_type)}`
                  : "Not selected"}
              </strong>
            </div>
          </div>

          {aiError ? <p className="policy-error-text">{aiError}</p> : null}
          {aiDraft ? (
            <div className="ai-draft-panel__content">
              <div className="policy-detail-grid">
                <div>
                  <span>Unmatched anomaly</span>
                  <strong>
                    {display(aiDraft.unmatched_anomaly?.id || selectedUnmatchedAnomaly?.id)} / window{" "}
                    {display(aiDraft.unmatched_anomaly?.window_id || selectedUnmatchedAnomaly?.window_id)}
                  </strong>
                </div>
                <div>
                  <span>Generation source</span>
                  <strong>{display(aiDraft.generation_source)}</strong>
                </div>
                <div>
                  <span>Validation result</span>
                  <strong>{aiDraft.validation?.valid ? "Valid" : "Invalid / needs review"}</strong>
                </div>
                <div>
                  <span>Model</span>
                  <strong>{display(aiDraft.model)}</strong>
                </div>
              </div>
              <pre className="policy-code-preview policy-code-preview--compact">
                <code>{aiDraft.draft_dsl || "No draft DSL returned."}</code>
              </pre>
              <div className="policy-message-list">
                {(aiDraft.warnings || []).map((warning, index) => (
                  <p key={`ai-warning-${index}`} className="policy-warning-text">
                    {warning}
                  </p>
                ))}
                {(aiDraft.validation?.errors || []).map((error, index) => (
                  <p key={`ai-error-${index}`} className="policy-error-text">
                    {error.message || String(error)}
                  </p>
                ))}
              </div>
              <div className="policy-action-row policy-action-row--wrap">
                <button className="action-button" type="button" onClick={copyDraftToEditor}>
                  Copy to Editor
                </button>
                <button className="action-button" type="button" onClick={saveDraftAsPolicy} disabled={!adminVerified || Boolean(actionBusy)}>
                  Save as Disabled Draft
                </button>
                <button className="action-button action-button--muted" type="button" onClick={() => setAiDraft(null)}>
                  Clear Draft
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="policy-action-row policy-action-row--wrap">
                <button
                  className="action-button action-button--primary"
                  type="button"
                  onClick={handleGenerateDraft}
                  disabled={!adminVerified || !selectedUnmatchedAnomaly || aiLoading}
                >
                  {aiLoading ? "Generating..." : "Generate AI Draft"}
                </button>
              </div>
              <EmptyState title="No AI draft generated">
                {currentScenarioEvidence
                  ? `Current evidence: ${currentScenarioEvidence.anomalyType || "Unknown"} anomaly on ${
                      currentScenarioEvidence.service || "unknown service"
                    }. Select an unmatched anomaly above to generate DSL from the backend AI endpoint.`
                  : "Select an unmatched anomaly above, verify the admin key, then click Generate AI Draft. The draft will appear here for review."}
              </EmptyState>
            </>
          )}
        </section>
      </section>

      <section className="panel policy-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Audit</p>
            <h2>Recent policy change audit</h2>
          </div>
          <div className="section-heading__meta">
            <span>{auditLoading ? "Loading audit" : auditError ? "Unavailable" : `${visibleAudit.length} events`}</span>
          </div>
        </div>

        {auditError ? (
          <EmptyState title="Policy change audit unavailable">{auditError}</EmptyState>
        ) : visibleAudit.length ? (
          <div className="change-audit-list">
            {visibleAudit.map((event, index) => (
              <article key={`${event.ts_utc || "audit"}-${index}`} className="change-audit-row">
                <span>{formatDateTime(event.ts_utc || event.timestamp)}</span>
                <span>{display(event.operation)}</span>
                <span>{display(event.policy_id)}</span>
                <span>{display(event.policy_name)}</span>
                <span>v{display(event.version)}</span>
                <span>{display(event.updated_by)}</span>
                <span>{display(event.reason)}</span>
                <span>{display(event.success ?? event.status ?? event.valid)}</span>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="No policy change audit events">Create, update, enable, disable, delete, or reload policies to populate audit.</EmptyState>
        )}
      </section>
    </div>
  );
}

export default PolicyStudio;
