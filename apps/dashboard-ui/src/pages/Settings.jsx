import PageHeader from "../components/PageHeader";

const CHANNELS = [
  {
    title: "Email alerts",
    purpose: "Route critical SmartOps incidents to operator inboxes.",
    triggers: "HIGH/CRITICAL anomalies, blocked policy decisions, verification failures",
  },
  {
    title: "WhatsApp alerts",
    purpose: "Send urgent mobile notifications for high-impact incidents.",
    triggers: "P1 policy outcomes, repeated recovery rate limits, verification failures",
  },
  {
    title: "Dashboard-only alerts",
    purpose: "Keep operational notices visible inside the SmartOps Control Center.",
    triggers: "Live API state, scenario evidence, unmatched anomaly review",
  },
];

const RECIPIENTS = [
  {
    name: "SRE Lead",
    role: "High-criticality incidents",
    email: "sre-lead@example.com",
    whatsapp: "+94 700 000 001",
    enabled: "No - example only",
    alertType: "P1 / CRITICAL",
  },
  {
    name: "DevOps Engineer",
    role: "Verification failures",
    email: "devops@example.com",
    whatsapp: "+94 700 000 002",
    enabled: "No - example only",
    alertType: "Verification failed",
  },
  {
    name: "Research Demo Owner",
    role: "Viva/demo alerts",
    email: "demo-owner@example.com",
    whatsapp: "+94 700 000 003",
    enabled: "No - example only",
    alertType: "Demo scenario",
  },
];

const ALERT_RULES = [
  ["Send when anomaly risk is HIGH or CRITICAL", "Email + WhatsApp", "High"],
  ["Send when policy decision is blocked", "Email + Dashboard", "High"],
  ["Send when verification fails", "Email + WhatsApp", "Critical"],
  ["Send when anomaly has no matching policy", "Dashboard", "Medium"],
  ["Send when repeated recovery actions are rate-limited", "Email + Dashboard", "High"],
  ["Send when policy priority is P1", "Email + WhatsApp", "Critical"],
];

const CONTRACTS = [
  "GET /api/notifications/settings",
  "POST /api/notifications/settings",
  "POST /api/notifications/test",
  "POST /api/notifications/send",
];

function Settings() {
  return (
    <div className="settings-page">
      <PageHeader
        eyebrow="Configuration"
        title="Settings & Notifications"
        description="Configure future alert routing for critical SmartOps incidents."
        meta={
          <>
            <span>Mode: Preview</span>
            <span>Email: Coming soon</span>
            <span>WhatsApp: Coming soon</span>
            <span>Secrets: Backend only</span>
            <span>Alert routing: Planned</span>
          </>
        }
      />

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Notification Channels</p>
            <h2>Planned alert routes</h2>
          </div>
        </div>

        <div className="settings-channel-grid">
          {CHANNELS.map((channel) => (
            <article key={channel.title} className="settings-card">
              <div className="settings-card__top">
                <h3>{channel.title}</h3>
                <span className="service-card__status service-card__status--configured">
                  Coming soon / UI preview
                </span>
              </div>
              <p>{channel.purpose}</p>
              <div className="settings-detail-list">
                <div>
                  <span>Planned trigger types</span>
                  <strong>{channel.triggers}</strong>
                </div>
              </div>
              <button className="action-button" type="button" disabled>
                Enable channel - Coming soon
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Recipients</p>
            <h2>Recipient routing preview</h2>
          </div>
          <div className="section-heading__meta">
            <span>Example only - not saved recipients</span>
          </div>
        </div>

        <div className="recipient-table">
          <div className="recipient-table__header">
            <span>Name</span>
            <span>Role</span>
            <span>Email</span>
            <span>WhatsApp number</span>
            <span>Enabled</span>
            <span>Alert type</span>
          </div>
          {RECIPIENTS.map((recipient) => (
            <article key={recipient.name} className="recipient-row">
              <span data-label="Name">{recipient.name}</span>
              <span data-label="Role">{recipient.role}</span>
              <span data-label="Email">{recipient.email}</span>
              <span data-label="WhatsApp number">{recipient.whatsapp}</span>
              <span data-label="Enabled">{recipient.enabled}</span>
              <span data-label="Alert type">{recipient.alertType}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="settings-split">
        <section className="panel settings-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Alert Rules</p>
              <h2>Planned routing rules</h2>
            </div>
          </div>

          <div className="alert-rule-list">
            {ALERT_RULES.map(([trigger, channel, severity]) => (
              <article key={trigger} className="alert-rule-row">
                <div>
                  <span>Trigger</span>
                  <strong>{trigger}</strong>
                </div>
                <div>
                  <span>Channel</span>
                  <strong>{channel}</strong>
                </div>
                <div>
                  <span>Severity</span>
                  <strong>{severity}</strong>
                </div>
                <span className="service-card__status service-card__status--configured">Planned</span>
              </article>
            ))}
          </div>
        </section>

        <section className="panel settings-section">
          <div className="section-heading">
            <div>
              <p className="section-heading__eyebrow">Test Notification</p>
              <h2>Delivery test preview</h2>
            </div>
          </div>

          <article className="settings-card settings-test-card">
            <h3>Send test notification</h3>
            <p>Requires backend notification service.</p>
            <p>This preview does not send real email or WhatsApp messages.</p>
            <button className="action-button action-button--primary" type="button" disabled>
              Send test notification - Coming soon
            </button>
          </article>
        </section>
      </section>

      <section className="panel settings-section settings-security-note">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Security</p>
            <h2>Notification credential handling</h2>
          </div>
        </div>

        <p>
          Notification credentials must be stored in backend services, Kubernetes secrets, or cloud
          secret managers. Credentials must never be stored in frontend code.
        </p>
        <div className="settings-security-grid">
          <article>Email providers may use SMTP, SendGrid, or Mailgun.</article>
          <article>WhatsApp may use Twilio or Meta WhatsApp Cloud API.</article>
          <article>Backend should handle rate limiting, audit logging, retries, and recipient authorization.</article>
        </div>
      </section>

      <section className="panel settings-section">
        <div className="section-heading">
          <div>
            <p className="section-heading__eyebrow">Backend Contract Preview</p>
            <h2>Planned notification API</h2>
          </div>
          <div className="section-heading__meta">
            <span>Backend not connected yet</span>
          </div>
        </div>

        <div className="api-contract-list">
          {CONTRACTS.map((endpoint) => (
            <article key={endpoint} className="api-contract-row">
              <code>{endpoint}</code>
              <span>Preview only - no frontend integration or sending behavior is implemented.</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default Settings;
