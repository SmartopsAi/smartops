export const DASHBOARD_ENV = "smartops-dev";

export const DASHBOARD_MODES = [
  { value: "live", label: "Live" },
  { value: "demo", label: "Demo" },
];

export const DASHBOARD_SYSTEMS = [
  { value: "erp-simulator", label: "ERP-simulator" },
  { value: "odoo", label: "Odoo" },
];

export const EXTERNAL_LINKS = {
  grafana: import.meta.env.VITE_GRAFANA_URL || "",
  prometheus: import.meta.env.VITE_PROMETHEUS_URL || "",
  odoo: import.meta.env.VITE_ODOO_URL || "",
};

export const REFRESH_INTERVALS = {
  live: 10000,
  demo: 5000,
};

