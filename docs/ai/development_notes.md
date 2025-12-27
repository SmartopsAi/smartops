# SmartOps – AI Development Notes

Author: Kulathunga K.A.K.M  
Project: SmartOps – AI-Driven Resilient ERP System

---

## Phase 0 – Foundation & Readiness

### Objective

Before developing AI models, we prepared the system to ensure:

- Clean data flow
- Reproducible experiments
- Lecturer-reviewable research design

---

### Step 0.1 – Telemetry Contract Definition

We defined a telemetry contract to clearly specify which signals the AI consumes.
This decouples AI models from ERP-specific metric names and improves generalization.

Artifacts:

- docs/ai/telemetry_contract.md

---

### Step 0.2 – Metric Normalization Layer

A normalization map was created to convert raw Prometheus metric names into
semantic AI-friendly signal names (e.g., memory_leak_bytes, cpu_burn_ms).

Artifacts:

- apps/agent-detect/collector/metric_map.py

Purpose:

- Prevent hard-coding ERP-specific metrics into AI models
- Support portability to other systems

---

### Step 0.3 – Ground Truth & Labeling Strategy

The ERP Simulator exposes a metric indicating active anomaly modes.
This metric is used as ground truth for labeling anomalies.

Labeling Rule:

- modes_enabled == 0 → NORMAL
- modes_enabled > 0 → ANOMALY

Artifacts:

- docs/ai/labeling_strategy.md

---

### Step 0.4 – Baseline Normal Data Collection

We captured a baseline dataset representing normal system behavior with all
chaos modes disabled.

Process:

- ERP Simulator was run with chaos OFF
- Metrics were collected every 5 seconds
- Data was stored as raw Prometheus text with timestamps

Artifacts:

- data/baseline/normal_run.json
- apps/agent-detect/tools/capture_baseline.py

Purpose:

- Learn normal behavior
- Calibrate thresholds
- Detect future drift

---

### Step 0.5 – Time Window & Sampling Strategy

We defined sampling and windowing parameters for continuous AI processing.

Decisions:

- Sampling interval: 5 seconds
- Window sizes: 60s (short-term), 300s (long-term)

Artifacts:

- docs/ai/time_windowing.md

---

### Step 0.6 – Ownership & Responsibility

AI services (agent-detect, agent-diagnose) are owned by Kulathunga.
Orchestrator and ERP simulator are managed separately.

Artifacts:

- apps/agent-detect/README.md

---

### Step 0.7 – Phase 1 Acceptance Criteria

Clear criteria were defined to determine successful completion of Phase 1.

Artifacts:

- docs/ai/phase1_acceptance.md

---

## Phase 0 Status

Phase 0 was completed successfully with all required documentation,
baseline datasets, and system readiness checks in place.
