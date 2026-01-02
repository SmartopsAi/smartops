Excellent work, Kulathunga 👍
What you shared is **already very strong**.
Below is a **clean, complete, lecturer-ready FULL DEVELOPMENT DOCUMENT**, continuing from your Phase 1 and **adding Phase 2 + External Dataset integration**, written in **academic yet practical language**.

You can **copy–paste this as a single document** (`docs/ai/development_notes.md`).

---

# **SmartOps – AI Development Notes**

**Author:** Kulathunga K.A.K.M
**Project:** SmartOps – AI-Driven Resilient ERP System
**Focus Area:** Continuous AI for Detection, Learning, and Root Cause Analysis

---

## **Phase 0 – Foundation & Readiness (COMPLETED)**

### **Objective**

Before developing AI models, the system was prepared to ensure:

* Clean and reliable data flow
* Reproducible experiments
* Clear separation between AI logic and system implementation
* Lecturer-reviewable research design

---

### **Step 0.1 – Telemetry Contract Definition**

A telemetry contract was defined to explicitly specify which signals are consumed by AI components.
This decouples AI models from ERP-specific metric names and improves portability.

**Artifacts**

* `docs/ai/telemetry_contract.md`

---

### **Step 0.2 – Metric Normalization Layer**

A normalization layer maps raw Prometheus metric names into semantic, AI-friendly signal names
(e.g., `cpu_burn_ms`, `memory_leak_bytes`, `request_count`).

**Artifacts**

* `apps/agent-detect/collector/metric_map.py`

**Purpose**

* Avoid hard-coded ERP-specific metrics
* Enable reuse of AI pipeline across systems

---

### **Step 0.3 – Ground Truth & Labeling Strategy**

The ERP Simulator exposes a metric indicating the number of active chaos modes.
This metric is used as **ground truth** for evaluation purposes.

**Labeling Rule**

* `modes_enabled == 0` → NORMAL
* `modes_enabled > 0` → ANOMALY

**Artifacts**

* `docs/ai/labeling_strategy.md`

---

### **Step 0.4 – Baseline Normal Data Collection**

A baseline dataset representing normal system behavior was captured.

**Process**

* ERP Simulator executed with all chaos modes disabled
* Metrics sampled every 5 seconds
* Raw Prometheus text stored with timestamps

**Artifacts**

* `data/baseline/normal_run.json`
* `apps/agent-detect/tools/capture_baseline.py`

**Purpose**

* Learn normal behavior
* Calibrate thresholds
* Detect future drift

---

### **Step 0.5 – Time Window & Sampling Strategy**

Sampling and windowing parameters were defined for continuous AI processing.

**Decisions**

* Sampling interval: 5 seconds
* Window sizes:

  * 60 seconds → fast anomaly detection
  * 300 seconds → slow degradation detection

**Artifacts**

* `docs/ai/time_windowing.md`

---

### **Step 0.6 – Ownership & Responsibility**

Clear ownership was defined to prevent architectural coupling.

* AI Agents (`agent-detect`, `agent-diagnose`) → Kulathunga
* Orchestrator & ERP Simulator → Separate ownership

**Artifacts**

* `apps/agent-detect/README.md`

---

### **Step 0.7 – Phase 1 Acceptance Criteria**

Formal acceptance criteria were defined to determine Phase 1 completion.

**Artifacts**

* `docs/ai/phase1_acceptance.md`

---

### **Phase 0 Status**

Phase 0 was completed successfully with all required documentation, baseline datasets,
and system readiness checks in place.

---

## **Phase 1 – Data Collection & Feature Pipeline (COMPLETED)**

### **Objective**

Build a **continuous, real-time, model-agnostic pipeline** that transforms raw telemetry
into AI-ready feature vectors.

---

### **Phase 1.1 – Streaming Data Collection**

* Continuous ingestion of ERP Simulator metrics
* Prometheus-format telemetry parsed into numeric time-series
* Metrics include CPU, memory, request count, and latency
* Logs and traces collected in pass-through mode for later RCA

**Artifacts**

* `collector/metrics_collector.py`
* `collector/prom_parser.py`
* `collector/metric_map.py`

---

### **Phase 1.2 – Data Grouping & Time Windowing**

* Sliding time windows implemented (60 seconds)
* Continuous window updates with overlap
* Bounded memory usage ensured

**Artifacts**

* `features/windowing.py`

---

### **Phase 1.3 – Continuous Feature Engineering**

For each window:

* Statistical features: mean, std, min, max
* Temporal features: trend slope
* Event indicators: spike detection

Produces fixed-length, model-agnostic feature vectors.

**Artifacts**

* `features/feature_engineering.py`

---

### **Phase 1.4 – Automatic Labeling Support**

* Ground truth (`modes_enabled`) attached to feature windows
* Labels used **only for evaluation**, never for detection

**Artifacts**

* `dataset/dataset_writer.py`

---

### **Phase 1.5 – Dataset Construction**

* Continuous dataset writer implemented
* Window-level feature vectors stored with timestamps and labels

**Artifacts**

* `data/datasets/features.csv`

---

### **Phase 1 Summary**

Phase 1 delivers a fully operational, continuously running feature pipeline that is
independent of anomaly detection models and ready for online AI and RCA.

---

## **Phase 2 – Anomaly Detection & Evaluation (COMPLETED)**

### **Objective**

Detect anomalies in real time using unsupervised models and quantitatively evaluate performance.

---

### **Phase 2.1 – Model Implementation**

Implemented two complementary models:

* **Statistical Baseline**

  * Mean & standard deviation thresholds
  * Conservative, high recall

* **Isolation Forest**

  * Unsupervised ensemble model
  * Better precision and stability

**Artifacts**

* `models/stats_baseline.py`
* `models/isolation_forest.py`

---

### **Phase 2.2 – Live Anomaly Detection**

* Models integrated into streaming pipeline
* Anomalies detected during chaos injection (CPU spike, latency jitter, memory leak)
* Recovery lag and false positives observed and analyzed

**Artifacts**

* `apps/agent-detect/app.py`

---

### **Phase 2.3 – Model Evaluation (Internal ERP Data)**

* Precision, Recall, TP, FP, FN computed
* Ground truth used **only for evaluation**

**Observed Behavior**

* Statistical Baseline → high recall, high false positives
* Isolation Forest → improved precision, stable detection

**Artifacts**

* `apps/agent-detect/eval/evaluate_models.py`

---

### **Phase 2.4 – External Dataset Integration**

Public anomaly detection datasets (AWS CloudWatch) were integrated offline.

* Multiple real cloud metrics (CPU, network, disk, request count)
* Heterogeneous timestamp formats normalized
* Same sliding window and feature engineering reused

**Artifacts**

* `apps/agent-detect/external/process_external_dataset.py`
* `data/datasets/aws_external_features.csv`

---

### **Phase 2.5 – External Dataset Evaluation**

Models were evaluated on AWS CloudWatch datasets to validate generalization.

**Outcome**

* Small number of labeled anomaly windows after aggregation
* Models did not over-trigger
* Pipeline correctness and robustness verified

**Artifacts**

* `apps/agent-detect/eval/evaluate_external_models.py`

---

### **Phase 2 Summary**

Phase 2 demonstrates that SmartOps can detect anomalies in real time, compare multiple models,
and generalize beyond the ERP simulator to real-world cloud datasets.

---

## **Current Project Status**

| Phase                            | Status      |
| -------------------------------- | ----------- |
| Phase 0 – Foundation             | ✅ Completed |
| Phase 1 – Data Pipeline          | ✅ Completed |
| Phase 2 – Detection & Evaluation | ✅ Completed |
| Phase 3 – Root Cause Analysis    | ⏭ Ready     |

---

## **Next Phase – Phase 3 (Planned)**

### **Phase 3 Objective**

Explain **why** anomalies occur by correlating:

* Metrics
* Logs
* Traces

Deliver human-readable Root Cause Analysis (RCA).

---

### **Planned Phase 3 Outputs**

* Log pattern extraction
* Trace dependency graphs
* Metric–log–trace correlation
* RCA reports for each detected anomaly



Great 👍
Below is a **clean, complete, lecturer-ready documentation update for PHASE 3**, written in the **same style and quality** as your Phase 0–2 notes.
You can **append this directly** to your existing *SmartOps – AI Development Notes* document.

---

# **Phase 3 – Root Cause Analysis (RCA) (COMPLETED)**

---

## **Phase 3 Objective**

The objective of Phase 3 is to move beyond anomaly detection and provide **explainable Root Cause Analysis (RCA)**.

While Phase 2 answers **“WHEN something goes wrong”**, Phase 3 answers:

* **WHY** the anomaly occurred
* **WHERE** it originated
* **WHAT evidence** supports the diagnosis

Phase 3 integrates **metrics, logs, and traces** to generate a **human-readable RCA report with confidence scoring**.

---

## **Phase 3 Architecture Overview**

```
Phase 2: Anomaly Detected
        ↓
Log Collection (Stage 3.2)
        ↓
Trace Analysis (Stage 3.3)
        ↓
Metric–Log–Trace Correlation (Stage 3.4)
        ↓
Root Cause Decision Logic (Stage 3.5)
        ↓
RCA Report Generation (Stage 3.6)
```

Phase 3 is **event-driven** and is executed **only when an anomaly is detected**, ensuring low overhead and clean separation of responsibilities.

---

## **Stage 3.1 – RCA Architecture & Contracts**

### Objective

Define a clear and enforceable **RCA contract** specifying:

* Inputs consumed by RCA
* Outputs produced by RCA
* Responsibilities of RCA components

This ensures transparency, reproducibility, and lecturer-reviewable logic.

### Key Design Decisions

* RCA is not a standalone service
* RCA is invoked automatically after anomaly detection
* Strong data contracts are enforced between stages

### Artifacts

* `apps/agent-diagnose/contracts.py`
* `apps/agent-diagnose/rca_engine.py`
* `apps/agent-diagnose/README.md`

### Output Contract (Conceptual)

```json
{
  "anomaly_id": "...",
  "timestamp": "...",
  "detected_anomaly": "...",
  "root_cause": {...},
  "evidence": {...},
  "confidence": 0.0
}
```

---

## **Stage 3.2 – Log Collection & Structuring**

### Objective

Convert unstructured application logs into **structured, time-aligned evidence** usable for RCA.

### Implementation

* Continuous log ingestion
* Severity classification (INFO, WARNING, ERROR)
* Timestamp-based querying aligned with anomaly windows

Logs are treated as **evidence**, not prediction signals.

### Artifacts

* `apps/agent-diagnose/logs/log_collector.py`
* `apps/agent-diagnose/logs/log_parser.py`
* `apps/agent-diagnose/logs/log_store.py`

### Example Structured Log

```json
{
  "timestamp": 1766821800,
  "severity": "ERROR",
  "message": "TimeoutError in OrderService"
}
```

---

## **Stage 3.3 – Trace Collection & Dependency Graphs**

### Objective

Identify **where failures propagate** by analyzing distributed traces.

### Implementation

* Span collection and normalization
* Service-to-service dependency graph construction
* Detection of high-latency propagation paths

Traces provide **causal paths**, not just symptoms.

### Artifacts

* `apps/agent-diagnose/traces/trace_collector.py`
* `apps/agent-diagnose/traces/trace_parser.py`
* `apps/agent-diagnose/traces/dependency_graph.py`

### Example Trace Evidence

```json
{
  "from": "OrderService",
  "to": "DatabaseService",
  "latency": 850
}
```

---

## **Stage 3.4 – Metric–Log–Trace Correlation**

### Objective

Correlate signals from different observability sources into a **single evidence set**.

### Correlation Strategy

* Metrics → primary anomaly indicators
* Logs → failure symptoms
* Traces → failure propagation paths

Correlation is **deterministic and explainable**, avoiding black-box reasoning.

### Artifacts

* `apps/agent-diagnose/correlation/correlator.py`
* `apps/agent-diagnose/correlation/signal_linker.py`

### Example Correlated Evidence

```json
{
  "metrics": ["cpu_burn_ms ↑", "request_count ↑"],
  "logs": ["TimeoutError in OrderService"],
  "traces": ["OrderService → DatabaseService (850ms)"]
}
```

---

## **Stage 3.5 – RCA Decision Logic**

### Objective

Infer the most likely root cause using **evidence-weighted reasoning**.

### Decision Strategy

* Metrics evidence (high weight)
* Trace evidence (high weight)
* Log evidence (medium weight)

Each independent signal contributes to a **confidence score**.

### Artifacts

* `apps/agent-diagnose/decision/rca_decider.py`

### Example Decision Output

```json
{
  "component": "DatabaseService",
  "type": "Resource Saturation",
  "signal": "cpu_burn_ms ↑",
  "confidence": 0.8
}
```

---

## **Stage 3.6 – RCA Output & Reporting**

### Objective

Generate final **human-readable and machine-readable RCA reports** and integrate RCA with anomaly detection.

### Implementation

* RCA report generation
* Console output for debugging and demonstrations
* JSON persistence for dashboards and analysis

### Artifacts

* `apps/agent-diagnose/reporter/rca_reporter.py`
* `apps/agent-diagnose/integrate_with_detect.py`
* `data/rca/*.json`

### Example RCA Report (Excerpt)

```
Root Cause:
  Component : DatabaseService
  Type      : Resource Saturation
  Signal    : cpu_burn_ms ↑

Evidence:
  Metrics: cpu_burn_ms ↑, request_count ↑
  Logs: TimeoutError in OrderService
  Traces: OrderService → DatabaseService (850ms)

Confidence Score: 1.0
```

---

## **Phase 3 Summary**

Phase 3 successfully extends SmartOps from anomaly detection to **explainable Root Cause Analysis**.

Key achievements:

* Event-driven RCA architecture
* Multi-signal evidence correlation
* Deterministic root cause inference
* Confidence-based explanations
* Clear separation between detection and diagnosis

This phase demonstrates **AIOps-level reasoning**, not just machine learning.

---

## **Overall Project Status**

| Phase                            | Status      |
| -------------------------------- | ----------- |
| Phase 0 – Foundation             | ✅ Completed |
| Phase 1 – Data Pipeline          | ✅ Completed |
| Phase 2 – Detection & Evaluation | ✅ Completed |
| Phase 3 – Root Cause Analysis    | ✅ Completed |

---
