const API_BASE_URL = import.meta.env.VITE_SMARTOPS_API_BASE_URL || "";

function extractApiErrorMessage(payload, response) {
  if (payload?.message) return payload.message;
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.errors) && payload.errors.length > 0) {
    return payload.errors
      .map((error) => {
        if (typeof error === "string") return error;
        const field = error?.field ? `${error.field}: ` : "";
        return `${field}${error?.message || error?.msg || JSON.stringify(error)}`;
      })
      .join("; ");
  }
  if (Array.isArray(payload?.validation?.errors) && payload.validation.errors.length > 0) {
    return payload.validation.errors
      .map((error) => {
        if (typeof error === "string") return error;
        const field = error?.field ? `${error.field}: ` : "";
        return `${field}${error?.message || error?.msg || JSON.stringify(error)}`;
      })
      .join("; ");
  }
  if (typeof payload === "string" && payload.trim()) return payload;
  return `Request failed: ${response.status} ${response.statusText}`;
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: options.headers || {},
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const error = new Error(extractApiErrorMessage(payload, response));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

function jsonHeaders(extraHeaders = {}) {
  return {
    "Content-Type": "application/json",
    ...extraHeaders,
  };
}

function adminHeaders(adminKey) {
  return jsonHeaders(adminKey ? { "X-SmartOps-Admin-Key": adminKey } : {});
}

export function getOverview() {
  return fetchJson("/api/overview");
}

export function getAnomalies() {
  return fetchJson("/api/anomalies");
}

export function getRca() {
  return fetchJson("/api/rca");
}

export function getPolicies() {
  return fetchJson("/api/policies");
}

export function getPolicyDecisions(limit = 10) {
  return fetchJson(`/api/policy/decisions?limit=${limit}`);
}

export function getServiceMetrics() {
  return fetchJson("/api/services/metrics");
}

export function getSignalsRecent(limit = 10) {
  return fetchJson(`/api/signals/recent?limit=${limit}`);
}

export function getDashboardState(
  system = "erp-simulator",
  limit = 10,
  scenarioKey = "",
  windowId = ""
) {
  const params = new URLSearchParams({
    system,
    limit: String(limit),
  });

  if (scenarioKey) {
    params.set("scenario_key", scenarioKey);
  }

  if (windowId) {
    params.set("window_id", windowId);
  }

  return fetchJson(`/api/dashboard/state?${params.toString()}`);
}

export function runScenario(payload) {
  return fetchJson("/api/scenarios/run", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export function runUnmatchedAnomalyDemo(adminKey) {
  return fetchJson("/api/demo/unmatched-anomaly/run", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify({}),
  });
}

export function triggerAction(payload) {
  return fetchJson("/api/actions/trigger", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export function verifyDeployment(payload) {
  return fetchJson("/api/verification", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export function verifyAdminKey(adminKey) {
  return fetchJson("/api/admin/verify", {
    headers: adminHeaders(adminKey),
  });
}

export function getPolicyDefinitions() {
  return fetchJson("/api/policies/definitions");
}

export function getPolicyDefinition(policyId) {
  return fetchJson(`/api/policies/definitions/${encodeURIComponent(policyId)}`);
}

export function validatePolicyDsl(payload) {
  return fetchJson("/api/policies/validate", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export function createPolicyDefinition(payload, adminKey) {
  return fetchJson("/api/policies/definitions", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function updatePolicyDefinition(policyId, payload, adminKey) {
  return fetchJson(`/api/policies/definitions/${encodeURIComponent(policyId)}`, {
    method: "PUT",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function deletePolicyDefinition(policyId, payload, adminKey) {
  return fetchJson(`/api/policies/definitions/${encodeURIComponent(policyId)}`, {
    method: "DELETE",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function enablePolicyDefinition(policyId, payload, adminKey) {
  return fetchJson(`/api/policies/definitions/${encodeURIComponent(policyId)}/enable`, {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function disablePolicyDefinition(policyId, payload, adminKey) {
  return fetchJson(`/api/policies/definitions/${encodeURIComponent(policyId)}/disable`, {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function reloadPolicies(payload, adminKey) {
  return fetchJson("/api/policies/reload", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function getPolicyChangeAudit(limit) {
  const suffix = limit ? `?limit=${encodeURIComponent(limit)}` : "";
  return fetchJson(`/api/policies/change-audit${suffix}`);
}

export function getUnmatchedAnomalies() {
  return fetchJson("/api/policies/unmatched-anomalies");
}

export function updateUnmatchedAnomalyStatus(id, payload, adminKey) {
  return fetchJson(`/api/policies/unmatched-anomalies/${encodeURIComponent(id)}/status`, {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function generatePolicyDraft(payload, adminKey) {
  const unmatchedId =
    typeof payload === "string"
      ? payload
      : payload?.unmatched_anomaly_id;

  if (!unmatchedId) {
    return Promise.reject(new Error("Select an unmatched anomaly before generating an AI draft."));
  }

  return fetchJson("/api/policies/generate-draft", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify({
      unmatched_anomaly_id: unmatchedId,
      constraints: {
        preferred_action: "auto",
        max_replicas: 4,
      },
    }),
  });
}

export function getNotificationSettings() {
  return fetchJson("/api/notifications/settings");
}

export function saveNotificationSettings(payload, adminKey) {
  return fetchJson("/api/notifications/settings", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function getNotificationAudit(limit) {
  const suffix = limit ? `?limit=${encodeURIComponent(limit)}` : "";
  return fetchJson(`/api/notifications/audit${suffix}`);
}

export function sendTestNotification(payload, adminKey) {
  return fetchJson("/api/notifications/test", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export function sendNotification(payload, adminKey) {
  return fetchJson("/api/notifications/send", {
    method: "POST",
    headers: adminHeaders(adminKey),
    body: JSON.stringify(payload),
  });
}

export { API_BASE_URL };
