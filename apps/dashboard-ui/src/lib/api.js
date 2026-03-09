const API_BASE_URL = import.meta.env.VITE_SMARTOPS_API_BASE_URL || "";

async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
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
    body: JSON.stringify(payload),
  });
}

export function triggerAction(payload) {
  return fetchJson("/api/actions/trigger", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function verifyDeployment(payload) {
  return fetchJson("/api/verification", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export { API_BASE_URL };
