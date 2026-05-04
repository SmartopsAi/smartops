import { useCallback, useEffect, useMemo, useState } from "react";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import {
  getNotificationAudit,
  getNotificationSettings,
  saveNotificationSettings,
  sendNotification,
  sendTestNotification,
  verifyAdminKey,
} from "../lib/api";

const CHANNEL_KEYS = ["dashboard", "email", "whatsapp"];
const ALERT_TYPES = ["HIGH_RISK", "POLICY_BLOCKED", "VERIFICATION_FAILED", "UNMATCHED_ANOMALY", "P1_PRIORITY"];
const SEVERITIES = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

const DEFAULT_CHANNELS = {
  dashboard: { enabled: true, mode: "internal" },
  email: { enabled: false, provider: "gmail_smtp", mode: "mock" },
  whatsapp: { enabled: false, provider: "twilio_whatsapp", mode: "mock" },
};

const DEFAULT_RECIPIENTS = [
  {
    id: "operator-primary",
    name: "Primary Operator",
    role: "Operator",
    email: "operator@example.com",
    whatsapp: "+94000000000",
    enabled: true,
    channels: ["dashboard"],
    alert_types: ["HIGH_RISK", "POLICY_BLOCKED", "VERIFICATION_FAILED", "UNMATCHED_ANOMALY"],
  },
];

const DEFAULT_RULES = {
  high_or_critical_anomaly: true,
  policy_blocked: true,
  verification_failed: true,
  unmatched_anomaly: true,
  p1_priority: true,
};

const DEFAULT_ALERT = {
  alert_type: "HIGH_RISK",
  severity: "HIGH",
  title: "SmartOps notification",
  message: "SmartOps alert notification from Settings page",
  service: "erp-simulator",
  window_id: "",
  channels: ["dashboard"],
};

const display = (value, fallback = "Not available") =>
  value === null || typeof value === "undefined" || value === "" ? fallback : value;

const coerceBoolean = (value, fallback = false) => {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes", "on"].includes(normalized)) return true;
    if (["false", "0", "no", "off"].includes(normalized)) return false;
  }
  if (typeof value === "undefined" || value === null) return fallback;
  return Boolean(value);
};

const normalizeArray = (value) => (Array.isArray(value) ? value : []);

const normalizeList = (payload, keys) => {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
};

const normalizeChannel = (defaults, channel = {}) => {
  const merged = { ...defaults, ...channel };
  return {
    ...merged,
    enabled: coerceBoolean(merged.enabled, defaults.enabled),
  };
};

const mergeChannels = (channels = {}) => ({
  dashboard: normalizeChannel(DEFAULT_CHANNELS.dashboard, channels.dashboard),
  email: normalizeChannel(DEFAULT_CHANNELS.email, channels.email),
  whatsapp: normalizeChannel(DEFAULT_CHANNELS.whatsapp, channels.whatsapp),
});

const channelChip = (channel) => {
  if (!channel?.enabled) return "Off";
  if (channel.mode === "real") return "Real";
  if (channel.mode === "internal") return "On";
  return "Mock";
};

const channelBadgeClass = (channel) =>
  !channel?.enabled
    ? "notification-badge notification-badge--off"
    : channel.mode === "real"
      ? "notification-badge notification-badge--real"
      : "notification-badge notification-badge--mock";

const safeSettings = (payload) => {
  const settings = payload?.settings || payload || {};
  const sourceRecipients =
    Array.isArray(settings.recipients) && settings.recipients.length ? settings.recipients : DEFAULT_RECIPIENTS;
  return {
    channels: mergeChannels(settings.channels),
    recipients: sourceRecipients.map((recipient) => ({
      ...recipient,
      enabled: coerceBoolean(recipient.enabled, true),
      channels: normalizeArray(recipient.channels),
      alert_types: normalizeArray(recipient.alert_types),
    })),
    rules: { ...DEFAULT_RULES, ...(settings.rules || {}) },
  };
};

const ruleForAlertType = (alertType) => {
  if (alertType === "UNMATCHED_ANOMALY") return "unmatched_anomaly";
  if (alertType === "POLICY_BLOCKED") return "policy_blocked";
  if (alertType === "VERIFICATION_FAILED") return "verification_failed";
  if (alertType === "P1_PRIORITY") return "p1_priority";
  if (alertType === "HIGH_RISK") return "high_or_critical_anomaly";
  return "";
};

function Settings() {
  const [adminKey, setAdminKey] = useState("");
  const [adminVerified, setAdminVerified] = useState(false);
  const [adminError, setAdminError] = useState("");

  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState("");
  const [channels, setChannels] = useState(DEFAULT_CHANNELS);
  const [recipients, setRecipients] = useState(DEFAULT_RECIPIENTS);
  const [rules, setRules] = useState(DEFAULT_RULES);

  const [auditEvents, setAuditEvents] = useState([]);
  const [auditLoading, setAuditLoading] = useState(true);
  const [auditError, setAuditError] = useState("");

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [sending, setSending] = useState(false);
  const [testChannels, setTestChannels] = useState(["dashboard"]);
  const [testMessage, setTestMessage] = useState("SmartOps test notification from Settings page");
  const [alertForm, setAlertForm] = useState(DEFAULT_ALERT);
  const [testResult, setTestResult] = useState(null);
  const [sendResult, setSendResult] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");

  const visibleAudit = useMemo(() => auditEvents.slice(0, 12), [auditEvents]);

  const getEligibleRecipients = useCallback(
    ({ channel, alertType = "UNMATCHED_ANOMALY" }) =>
      recipients.filter((recipient) => {
        if (!coerceBoolean(recipient.enabled, true)) return false;
        if (!normalizeArray(recipient.channels).includes(channel)) return false;
        if (alertType !== "TEST" && !normalizeArray(recipient.alert_types).includes(alertType)) return false;
        if (channel === "email") return Boolean(recipient.email);
        if (channel === "whatsapp") return Boolean(recipient.whatsapp);
        return true;
      }),
    [recipients]
  );

  const getChannelRoute = useCallback(
    ({ channel, alertType = "UNMATCHED_ANOMALY", selectedChannels = CHANNEL_KEYS }) => {
      const selected = normalizeArray(selectedChannels);
      const channelConfig = channels[channel] || {};
      const ruleKey = ruleForAlertType(alertType);
      const eligibleRecipients = getEligibleRecipients({ channel, alertType });

      if (!selected.includes(channel)) {
        return { channel, willSend: false, recipients: eligibleRecipients, reason: "channel not selected" };
      }
      if (!coerceBoolean(channelConfig.enabled, false)) {
        return { channel, willSend: false, recipients: eligibleRecipients, reason: "channel disabled" };
      }
      if (ruleKey && !coerceBoolean(rules[ruleKey], true)) {
        return { channel, willSend: false, recipients: eligibleRecipients, reason: `${ruleKey} rule disabled` };
      }
      if (!eligibleRecipients.length) {
        return { channel, willSend: false, recipients: eligibleRecipients, reason: `no eligible ${channel} recipients` };
      }

      const mode = channelConfig.mode || (channel === "dashboard" ? "internal" : "mock");
      const provider = channelConfig.provider ? ` via ${channelConfig.provider}` : "";
      return {
        channel,
        willSend: true,
        recipients: eligibleRecipients,
        reason: channel === "dashboard" ? "enabled internal dashboard route" : `${mode}${provider}`,
      };
    },
    [channels, getEligibleRecipients, rules]
  );

  const unmatchedRoutingSummary = useMemo(
    () =>
      CHANNEL_KEYS.map((channel) =>
        getChannelRoute({
          channel,
          alertType: "UNMATCHED_ANOMALY",
          selectedChannels: CHANNEL_KEYS,
        })
      ),
    [getChannelRoute]
  );

  const testRoutingSummary = useMemo(
    () =>
      CHANNEL_KEYS.map((channel) =>
        getChannelRoute({
          channel,
          alertType: "TEST",
          selectedChannels: testChannels,
        })
      ),
    [getChannelRoute, testChannels]
  );

  const alertRoutingSummary = useMemo(
    () =>
      CHANNEL_KEYS.map((channel) =>
        getChannelRoute({
          channel,
          alertType: alertForm.alert_type,
          selectedChannels: alertForm.channels,
        })
      ),
    [alertForm.alert_type, alertForm.channels, getChannelRoute]
  );

  const loadSettings = useCallback(async () => {
    try {
      setSettingsLoading(true);
      const payload = await getNotificationSettings();
      const normalized = safeSettings(payload);
      setChannels(normalized.channels);
      setRecipients(normalized.recipients);
      setRules(normalized.rules);
      setSettingsError("");
    } catch (err) {
      setChannels(DEFAULT_CHANNELS);
      setRecipients(DEFAULT_RECIPIENTS);
      setRules(DEFAULT_RULES);
      setSettingsError(err.message || "Notification settings API unavailable.");
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async () => {
    try {
      setAuditLoading(true);
      const payload = await getNotificationAudit(25);
      const events = normalizeList(payload, ["events", "audit", "items", "results"]);
      setAuditEvents(events.slice().reverse());
      setAuditError("");
    } catch (err) {
      setAuditEvents([]);
      setAuditError(err.message || "Notification audit API unavailable.");
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const refreshData = useCallback(async () => {
    await Promise.all([loadSettings(), loadAudit()]);
  }, [loadAudit, loadSettings]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  const requireAdmin = () => {
    if (!adminKey.trim()) {
      setActionError("Admin API key is required for this action.");
      return false;
    }
    return true;
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
      const verified = Boolean(payload?.admin || payload?.status === "ok");
      setAdminVerified(verified);
      if (!verified) setAdminError("Admin verification did not return an approved status.");
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

  const updateChannel = (key, patch) => {
    setChannels((current) => ({
      ...current,
      [key]: { ...(current[key] || {}), ...patch },
    }));
  };

  const updateRecipient = (index, patch) => {
    setRecipients((current) => current.map((recipient, i) => (i === index ? { ...recipient, ...patch } : recipient)));
  };

  const toggleRecipientArrayValue = (index, field, value) => {
    setRecipients((current) =>
      current.map((recipient, i) => {
        if (i !== index) return recipient;
        const values = new Set(recipient[field] || []);
        if (values.has(value)) values.delete(value);
        else values.add(value);
        return { ...recipient, [field]: Array.from(values) };
      })
    );
  };

  const addRecipient = () => {
    setRecipients((current) => [
      ...current,
      {
        id: `operator-${current.length + 1}`,
        name: "New Operator",
        role: "Operator",
        email: "",
        whatsapp: "",
        enabled: true,
        channels: ["dashboard"],
        alert_types: ["HIGH_RISK"],
      },
    ]);
  };

  const removeRecipient = (index) => {
    setRecipients((current) => current.filter((_, i) => i !== index));
  };

  const toggleRule = (key) => {
    setRules((current) => ({ ...current, [key]: !current[key] }));
  };

  const toggleChannelSelection = (value, setter) => {
    setter((current) => {
      const selected = new Set(current);
      if (selected.has(value)) selected.delete(value);
      else selected.add(value);
      return Array.from(selected);
    });
  };

  const handleSaveSettings = async () => {
    if (!requireAdmin()) return;
    try {
      setSaving(true);
      setActionError("");
      setActionMessage("");
      await saveNotificationSettings(
        {
          updated_by: "operator",
          channels,
          recipients,
          rules,
        },
        adminKey.trim()
      );
      setActionMessage("Notification settings saved.");
      await refreshData();
    } catch (err) {
      setActionError(err.message || "Failed to save notification settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleSendTest = async () => {
    if (!requireAdmin()) return;
    try {
      setTesting(true);
      setActionError("");
      setTestResult(null);
      const result = await sendTestNotification(
        {
          channels: testChannels,
          message: testMessage,
          updated_by: "operator",
        },
        adminKey.trim()
      );
      setTestResult(result);
      setActionMessage("Test notification request completed.");
      await loadAudit();
    } catch (err) {
      setActionError(err.message || "Failed to send test notification.");
    } finally {
      setTesting(false);
    }
  };

  const handleSendAlert = async () => {
    if (!requireAdmin()) return;
    try {
      setSending(true);
      setActionError("");
      setSendResult(null);
      const result = await sendNotification(
        {
          ...alertForm,
          updated_by: "operator",
        },
        adminKey.trim()
      );
      setSendResult(result);
      setActionMessage("Alert notification request completed.");
      await loadAudit();
    } catch (err) {
      setActionError(err.message || "Failed to send alert notification.");
    } finally {
      setSending(false);
    }
  };

  const renderChannelCheckboxes = (selected, setter) => (
    <div className="settings-checkbox-row">
      {CHANNEL_KEYS.map((channel) => (
        <label key={channel}>
          <input
            type="checkbox"
            checked={normalizeArray(selected).includes(channel)}
            onChange={() => toggleChannelSelection(channel, setter)}
          />
          <span>{channel}</span>
        </label>
      ))}
    </div>
  );

  const renderRouteSummary = (summary) => (
    <div className="settings-route-summary">
      {summary.map((route) => (
        <article key={route.channel}>
          <span>{route.channel}</span>
          <strong>{route.willSend ? "Yes" : "No"}</strong>
          <small>{route.reason}</small>
          <small>
            Recipients: {route.recipients.map((recipient) => recipient.name || recipient.id).join(", ") || "None"}
          </small>
        </article>
      ))}
    </div>
  );

  const renderResult = (result) => {
    if (!result) return null;
    return (
      <div className="settings-result-panel">
        <div className="settings-result-panel__summary">
          <span className={result.status === "ok" ? "notification-badge notification-badge--real" : "notification-badge notification-badge--off"}>
            {display(result.status)}
          </span>
          <span>Mode: {display(result.mode)}</span>
          <span>Sent: {String(Boolean(result.sent))}</span>
          <span>Mocked: {String(Boolean(result.mocked))}</span>
        </div>
        {result.preview ? (
          <div className="settings-detail-list">
            <div>
              <span>Preview</span>
              <strong>
                {display(result.preview.title)} - {display(result.preview.message)}
              </strong>
            </div>
            <div>
              <span>Recipients</span>
              <strong>{(result.preview.recipients || []).map((item) => item.name || item.id).join(", ") || "None"}</strong>
            </div>
          </div>
        ) : null}
        <div className="settings-channel-results">
          {(result.channel_results || []).map((item, index) => (
            <article key={`${item.channel}-${index}`}>
              <strong>
                {display(item.channel)} {item.provider ? `(${item.provider})` : ""}
              </strong>
              <span>Mode: {display(item.mode)}</span>
              <span>Sent: {String(Boolean(item.sent))}</span>
              <span>Recipients: {display(item.recipient_count, "0")}</span>
              {item.message_sids?.length ? <span>Message SIDs: {item.message_sids.join(", ")}</span> : null}
              {item.error ? <span className="settings-error-text">Error: {item.error}</span> : null}
            </article>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="settings-page">
      <PageHeader
        eyebrow="Configuration"
        title="Settings & Notifications"
        description="Configure future and live alert routing for critical SmartOps incidents."
        meta={
          <>
            <span>Admin: {adminVerified ? "Verified" : "Not verified"}</span>
            <span>Dashboard: {channelChip(channels.dashboard)}</span>
            <span>Email: {channelChip(channels.email)}</span>
            <span>WhatsApp: {channelChip(channels.whatsapp)}</span>
            <span>Recipients: {recipients.length}</span>
            <span>Audit: {auditEvents.length}</span>
          </>
        }
      />

      <section className="settings-grid">
        <section className="panel settings-section settings-admin-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Admin Access</p>
              <h2>Protected notification actions</h2>
            </div>
            <span className={adminVerified ? "notification-badge notification-badge--real" : "notification-badge notification-badge--off"}>
              {adminVerified ? "Verified" : "Not verified"}
            </span>
          </div>

          <label className="settings-field">
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
          <div className="settings-action-row">
            <button className="action-button" type="button" onClick={handleVerifyAdmin} disabled={!adminKey.trim()}>
              Verify Admin Key
            </button>
            <button className="action-button action-button--muted" type="button" onClick={handleClearAdmin}>
              Clear
            </button>
          </div>
          {adminError ? <p className="settings-error-text">{adminError}</p> : null}
          <p className="settings-muted-text">
            The admin key stays only in React state for this page session. Provider secrets remain backend/Kubernetes secrets only.
          </p>
        </section>

        <section className="panel settings-section provider-status-card">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Provider Status</p>
              <h2>Delivery provider notes</h2>
            </div>
          </div>
          <div className="settings-provider-list">
            <article>WhatsApp real delivery is available via Twilio when backend secrets are configured; live cluster testing has verified delivery.</article>
            <article>Gmail SMTP is implemented, but DigitalOcean may block SMTP ports 25, 465, and 587.</article>
            <article>SendGrid HTTPS is the recommended cloud email path because it uses HTTPS 443.</article>
            <article>Secrets are stored in Kubernetes/backend only; never in frontend code or settings JSON.</article>
          </div>
        </section>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Automatic Routing</p>
            <h2>UNMATCHED_ANOMALY route summary</h2>
          </div>
        </div>
        <div className="settings-route-summary settings-route-summary--three">
          <article>
            <span>Dashboard will record</span>
            <strong>{unmatchedRoutingSummary.find((route) => route.channel === "dashboard")?.willSend ? "Yes" : "No"}</strong>
            <small>{unmatchedRoutingSummary.find((route) => route.channel === "dashboard")?.reason}</small>
          </article>
          <article>
            <span>Email will be sent</span>
            <strong>{unmatchedRoutingSummary.find((route) => route.channel === "email")?.willSend ? "Yes" : "No"}</strong>
            <small>{unmatchedRoutingSummary.find((route) => route.channel === "email")?.reason}</small>
          </article>
          <article>
            <span>WhatsApp will be sent</span>
            <strong>{unmatchedRoutingSummary.find((route) => route.channel === "whatsapp")?.willSend ? "Yes" : "No"}</strong>
            <small>{unmatchedRoutingSummary.find((route) => route.channel === "whatsapp")?.reason}</small>
          </article>
        </div>
        <p className="settings-muted-text">
          If email test succeeds but automatic email does not, check channel enabled, recipient channel, alert rule, and the audit channel result.
        </p>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Notification Channels</p>
            <h2>Channel settings</h2>
          </div>
          <div className="section-heading__meta">
            <span>{settingsLoading ? "Loading settings" : settingsError ? "Fallback defaults" : "Backend settings"}</span>
          </div>
        </div>

        {settingsError ? <p className="settings-error-text">{settingsError}</p> : null}

        <div className="settings-channel-grid">
          <article className="settings-channel-card">
            <div className="settings-card__top">
              <h3>Dashboard-only alerts</h3>
              <span className={channelBadgeClass(channels.dashboard)}>{channelChip(channels.dashboard)}</span>
            </div>
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={Boolean(channels.dashboard.enabled)}
                onChange={(event) => updateChannel("dashboard", { enabled: event.target.checked, mode: "internal" })}
              />
              <span>Enabled</span>
            </label>
            <p>Mode: internal. Dashboard channel records routing intent without external provider secrets.</p>
          </article>

          <article className="settings-channel-card">
            <div className="settings-card__top">
              <h3>Email alerts</h3>
              <span className={channelBadgeClass(channels.email)}>{channelChip(channels.email)}</span>
            </div>
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={Boolean(channels.email.enabled)}
                onChange={(event) => updateChannel("email", { enabled: event.target.checked })}
              />
              <span>Enabled</span>
            </label>
            <label className="settings-field">
              <span>Provider</span>
              <select value={channels.email.provider || "gmail_smtp"} onChange={(event) => updateChannel("email", { provider: event.target.value })}>
                <option value="gmail_smtp">gmail_smtp</option>
                <option value="sendgrid">sendgrid</option>
              </select>
            </label>
            <label className="settings-field">
              <span>Mode</span>
              <select value={channels.email.mode || "mock"} onChange={(event) => updateChannel("email", { mode: event.target.value })}>
                <option value="mock">mock</option>
                <option value="real">real</option>
              </select>
            </label>
            <p>Provider secrets are stored only in Kubernetes/backend environment variables.</p>
          </article>

          <article className="settings-channel-card">
            <div className="settings-card__top">
              <h3>WhatsApp alerts</h3>
              <span className={channelBadgeClass(channels.whatsapp)}>{channelChip(channels.whatsapp)}</span>
            </div>
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={Boolean(channels.whatsapp.enabled)}
                onChange={(event) => updateChannel("whatsapp", { enabled: event.target.checked })}
              />
              <span>Enabled</span>
            </label>
            <label className="settings-field">
              <span>Provider</span>
              <select value={channels.whatsapp.provider || "twilio_whatsapp"} onChange={(event) => updateChannel("whatsapp", { provider: event.target.value })}>
                <option value="twilio_whatsapp">twilio_whatsapp</option>
              </select>
            </label>
            <label className="settings-field">
              <span>Mode</span>
              <select value={channels.whatsapp.mode || "mock"} onChange={(event) => updateChannel("whatsapp", { mode: event.target.value })}>
                <option value="mock">mock</option>
                <option value="real">real</option>
              </select>
            </label>
            <p>Twilio WhatsApp Sandbox/Business credentials are backend secrets.</p>
          </article>
        </div>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Recipients</p>
            <h2>Recipient routing</h2>
          </div>
          <button className="action-button" type="button" onClick={addRecipient}>
            Add recipient
          </button>
        </div>

        <div className="settings-recipient-list">
          {recipients.map((recipient, index) => (
            <article key={`${recipient.id}-${index}`} className="settings-recipient-card">
              <div className="settings-recipient-card__top">
                <h3>{display(recipient.name, "Unnamed recipient")}</h3>
                <button className="action-button action-button--danger" type="button" onClick={() => removeRecipient(index)}>
                  Remove
                </button>
              </div>
              <div className="settings-recipient-fields">
                {["id", "name", "role", "email", "whatsapp"].map((field) => (
                  <label key={field} className="settings-field">
                    <span>{field}</span>
                    <input value={recipient[field] || ""} onChange={(event) => updateRecipient(index, { [field]: event.target.value })} />
                  </label>
                ))}
                <label className="settings-toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(recipient.enabled)}
                    onChange={(event) => updateRecipient(index, { enabled: event.target.checked })}
                  />
                  <span>Enabled</span>
                </label>
              </div>
              <div className="settings-recipient-options">
                <div>
                  <span>Channels</span>
                  <div className="settings-checkbox-row">
                    {CHANNEL_KEYS.map((channel) => (
                      <label key={channel}>
                        <input
                          type="checkbox"
                          checked={(recipient.channels || []).includes(channel)}
                          onChange={() => toggleRecipientArrayValue(index, "channels", channel)}
                        />
                        <span>{channel}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <span>Alert types</span>
                  <div className="settings-checkbox-row settings-checkbox-row--dense">
                    {ALERT_TYPES.map((type) => (
                      <label key={type}>
                        <input
                          type="checkbox"
                          checked={(recipient.alert_types || []).includes(type)}
                          onChange={() => toggleRecipientArrayValue(index, "alert_types", type)}
                        />
                        <span>{type}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="settings-grid">
        <section className="panel settings-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Alert Rules</p>
              <h2>Routing conditions</h2>
            </div>
          </div>
          <div className="settings-rule-grid">
            {Object.keys(DEFAULT_RULES).map((rule) => (
              <label key={rule} className="settings-rule-card">
                <input type="checkbox" checked={Boolean(rules[rule])} onChange={() => toggleRule(rule)} />
                <span>{rule}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="panel settings-section settings-action-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Save</p>
              <h2>Persist notification settings</h2>
            </div>
          </div>
          <p className="settings-muted-text">Only routing metadata is saved. Provider secrets are never sent from the frontend.</p>
          <button className="action-button action-button--primary" type="button" onClick={handleSaveSettings} disabled={!adminKey.trim() || saving}>
            {saving ? "Saving..." : "Save Notification Settings"}
          </button>
          {actionMessage ? <p className="settings-success-text">{actionMessage}</p> : null}
          {actionError ? <p className="settings-error-text">{actionError}</p> : null}
        </section>
      </section>

      <section className="settings-grid">
        <section className="panel settings-section settings-action-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Test Notification</p>
              <h2>Send explicit test</h2>
            </div>
          </div>
          <div className="settings-field">
            <span>Channels</span>
            {renderChannelCheckboxes(testChannels, setTestChannels)}
          </div>
          <div className="settings-field">
            <span>Selected route preview</span>
            {renderRouteSummary(testRoutingSummary)}
          </div>
          <label className="settings-field">
            <span>Message</span>
            <textarea value={testMessage} onChange={(event) => setTestMessage(event.target.value)} />
          </label>
          <button className="action-button action-button--primary" type="button" onClick={handleSendTest} disabled={!adminKey.trim() || testing}>
            {testing ? "Sending..." : "Send Test Notification"}
          </button>
          {renderResult(testResult)}
        </section>

        <section className="panel settings-section settings-action-panel">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Manual Alert</p>
              <h2>Send alert notification</h2>
            </div>
          </div>
          <div className="settings-alert-form">
            <label className="settings-field">
              <span>Alert type</span>
              <select value={alertForm.alert_type} onChange={(event) => setAlertForm((current) => ({ ...current, alert_type: event.target.value }))}>
                {[...ALERT_TYPES, "TEST"].map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label className="settings-field">
              <span>Severity</span>
              <select value={alertForm.severity} onChange={(event) => setAlertForm((current) => ({ ...current, severity: event.target.value }))}>
                {SEVERITIES.map((severity) => (
                  <option key={severity} value={severity}>
                    {severity}
                  </option>
                ))}
              </select>
            </label>
            {["title", "service", "window_id"].map((field) => (
              <label key={field} className="settings-field">
                <span>{field}</span>
                <input value={alertForm[field]} onChange={(event) => setAlertForm((current) => ({ ...current, [field]: event.target.value }))} />
              </label>
            ))}
            <label className="settings-field settings-alert-form__message">
              <span>Message</span>
              <textarea value={alertForm.message} onChange={(event) => setAlertForm((current) => ({ ...current, message: event.target.value }))} />
            </label>
            <div className="settings-field settings-alert-form__message">
              <span>Channels</span>
              {renderChannelCheckboxes(alertForm.channels, (updater) =>
                setAlertForm((current) => ({
                  ...current,
                  channels: typeof updater === "function" ? updater(current.channels) : updater,
                }))
              )}
            </div>
            <div className="settings-field settings-alert-form__message">
              <span>Selected route preview</span>
              {renderRouteSummary(alertRoutingSummary)}
            </div>
          </div>
          <button className="action-button action-button--primary" type="button" onClick={handleSendAlert} disabled={!adminKey.trim() || sending}>
            {sending ? "Sending..." : "Send Alert Notification"}
          </button>
          {renderResult(sendResult)}
        </section>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Audit</p>
            <h2>Notification audit</h2>
          </div>
          <div className="section-heading__meta">
            <span>{auditLoading ? "Loading audit" : auditError ? "Unavailable" : `${visibleAudit.length} events`}</span>
            <button className="action-button action-button--muted" type="button" onClick={loadAudit}>
              Refresh Audit
            </button>
          </div>
        </div>

        {auditError ? (
          <EmptyState title="Notification audit unavailable">{auditError}</EmptyState>
        ) : visibleAudit.length ? (
          <div className="settings-audit-list">
            {visibleAudit.map((event, index) => (
              <article key={`${event.ts_utc || "audit"}-${index}`} className="settings-audit-row">
                <span>{display(event.operation)}</span>
                <span>{display(event.alert_type)}</span>
                <span>{(event.channels || []).join(", ") || "None"}</span>
                <span>{display(event.recipient_count, "0")}</span>
                <span>{display(event.status)}</span>
                <span>{display(event.updated_by)}</span>
                <span>{display(event.ts_utc)}</span>
                <span>{display(event.message)}</span>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="No notification audit events">Save settings or send a test notification to populate audit.</EmptyState>
        )}
      </section>
    </div>
  );
}

export default Settings;
