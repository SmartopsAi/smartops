const iconProps = {
  width: "22",
  height: "22",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: "1.8",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  focusable: "false",
};

const DockIcons = {
  live: (
    <svg {...iconProps} aria-hidden="true">
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <path d="m7 15 3.2-3.2 2.6 2.6L18 8" />
      <path d="M18 8h-3.5" />
      <path d="M18 8v3.5" />
    </svg>
  ),
  demo: (
    <svg {...iconProps} aria-hidden="true">
      <path d="M9 3h6" />
      <path d="M10 3v5.2L5.7 17a3 3 0 0 0 2.7 4.3h7.2a3 3 0 0 0 2.7-4.3L14 8.2V3" />
      <path d="M8.2 15h7.6" />
      <path d="m10.5 11 3 2-3 2v-4Z" />
    </svg>
  ),
  policy: (
    <svg {...iconProps} aria-hidden="true">
      <path d="M12 3 5 6v5.2c0 4.1 2.8 7.9 7 9.8 4.2-1.9 7-5.7 7-9.8V6l-7-3Z" />
      <path d="m9 12 2 2 4-5" />
    </svg>
  ),
  evidence: (
    <svg {...iconProps} aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3 2" />
      <path d="M4 20h16" />
    </svg>
  ),
  integrations: (
    <svg {...iconProps} aria-hidden="true">
      <path d="M8 7H6a4 4 0 0 0 0 8h2" />
      <path d="M16 7h2a4 4 0 0 1 0 8h-2" />
      <path d="M8.5 12h7" />
      <path d="M10 5v4" />
      <path d="M14 15v4" />
    </svg>
  ),
  settings: (
    <svg {...iconProps} aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 0 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.3 7A2 2 0 0 1 7.1 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 0 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.1a2 2 0 0 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </svg>
  ),
};

const NAV_ITEMS = [
  { key: "live", label: "Live Dashboard", icon: DockIcons.live },
  { key: "demo", label: "Demo Lab", icon: DockIcons.demo },
  { key: "policy", label: "Policy Studio", icon: DockIcons.policy },
  { key: "evidence", label: "Evidence Timeline", icon: DockIcons.evidence },
  { key: "integrations", label: "Integrations", icon: DockIcons.integrations },
  { key: "settings", label: "Settings", icon: DockIcons.settings },
];

function HoverDock({ activePage, onPageChange }) {
  return (
    <nav className="hover-dock" aria-label="SmartOps sections">
      <div className="hover-dock__brand" aria-hidden="true">
        SO
      </div>
      <div className="hover-dock__items">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`hover-dock__item ${activePage === item.key ? "hover-dock__item--active" : ""}`}
            onClick={() => onPageChange(item.key)}
            aria-current={activePage === item.key ? "page" : undefined}
            aria-label={item.label}
            title={item.label}
          >
            <span className="hover-dock__icon" aria-hidden="true">
              {item.icon}
            </span>
            <span className="hover-dock__label">{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

export default HoverDock;
