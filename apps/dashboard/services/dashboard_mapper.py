from typing import Any, Dict, List, Optional


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _stringify(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    return str(value)


def _safe_round(value: Any, digits: int = 2) -> Any:
    if isinstance(value, (int, float)):
        return round(value, digits)
    return value


def _humanize_policy_name(policy_name: Any) -> str:
    value = _stringify(policy_name, "")
    if not value:
        return "-"
    mapping = {
        "scale_up_on_anomaly_resource_step_1": "Resource anomaly scale-up",
        "restart_on_anomaly_error": "Error anomaly restart",
        "manual_scale": "Manual scale",
        "manual_restart": "Manual restart",
    }
    return mapping.get(value, value.replace("_", " ").title())


def _humanize_decision_policy(policy_decision: Optional[Dict[str, Any]]) -> str:
    if not policy_decision:
        return "-"
    decision_value = str(policy_decision.get("decision", "")).lower()
    policy_label = _humanize_policy_name(policy_decision.get("policy"))
    guardrail = _stringify(policy_decision.get("guardrail_reason"), "")

    if decision_value == "blocked" and "restart cooldown" in guardrail.lower():
        return "Restart cooldown guardrail"

    return policy_label


def build_system_state(
    *,
    system: str,
    mode: str,
    deployment: str,
    namespace: str,
    connected: bool,
    health_status: str,
    latency_p95_ms: Optional[float] = None,
    replicas_desired: Optional[int] = None,
    replicas_ready: Optional[int] = None,
    replicas_available: Optional[int] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "system": system,
        "mode": mode,
        "deployment": deployment,
        "namespace": namespace,
        "connected": connected,
        "health": health_status,
        "latencyP95Ms": latency_p95_ms,
        "replicasDesired": replicas_desired,
        "replicasReady": replicas_ready,
        "replicasAvailable": replicas_available,
        "note": note,
    }


def build_summary_cards(
    *,
    system_state: Dict[str, Any],
    anomaly: Optional[Dict[str, Any]] = None,
    rca: Optional[Dict[str, Any]] = None,
    policy_decision: Optional[Dict[str, Any]] = None,
    verification: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    system = system_state.get("system", "unknown")
    is_odoo = system == "odoo"

    cards: List[Dict[str, str]] = [
        {"label": "System", "value": system_state.get("system", "-"), "tone": "info"},
    ]

    if is_odoo:
        cards.extend(
            [
                {
                    "label": "Connected",
                    "value": "Connected" if system_state.get("connected") else "Disconnected",
                    "tone": "success" if system_state.get("connected") else "warning",
                },
                {
                    "label": "Health",
                    "value": _stringify(system_state.get("health", "-")).title(),
                    "tone": "success" if system_state.get("health") == "healthy" else "warning",
                },
                {"label": "Detection", "value": "Monitoring only", "tone": "info"},
                {
                    "label": "Diagnosis",
                    "value": "RCA skipped" if not rca else "Available",
                    "tone": "warning" if not rca else "success",
                },
                {
                    "label": "Anomaly State",
                    "value": "No active anomaly" if not anomaly else "Anomaly detected",
                    "tone": "neutral" if not anomaly else "warning",
                },
                {
                    "label": "Plug-in Note",
                    "value": system_state.get("note") or "ERP plug-in demonstration",
                    "tone": "info",
                },
            ]
        )
        return cards

    replicas_ready = _coalesce(system_state.get("replicasReady"), 0)
    replicas_desired = _coalesce(system_state.get("replicasDesired"), 0)
    verification_value = "Not available"
    verification_tone = "neutral"

    if policy_decision and str(policy_decision.get("decision", "")).lower() == "blocked":
        verification_value = "Not required"
        verification_tone = "neutral"
    elif policy_decision and ((policy_decision.get("action_plan") or {}).get("verify")) and not verification:
        verification_value = "Waiting"
        verification_tone = "warning"
    elif verification:
        verification_status = verification.get("status")
        overall = verification.get("overall")

        if verification_status == "pending" or overall is None:
            verification_value = "Pending"
            verification_tone = "warning"
        elif overall is True:
            verification_value = "Passed"
            verification_tone = "success"
        else:
            verification_value = "Failed"
            verification_tone = "error"

    cards.extend(
        [
            {
                "label": "Health",
                "value": _stringify(system_state.get("health", "-")).title(),
                "tone": "success" if system_state.get("health") == "healthy" else "warning",
            },
            {
                "label": "Anomaly State",
                "value": "No active anomaly" if not anomaly else "Anomaly detected",
                "tone": "neutral" if not anomaly else "warning",
            },
            {
                "label": "RCA State",
                "value": "No diagnosis available" if not rca else "Diagnosis available",
                "tone": "neutral" if not rca else "info",
            },
            {
                "label": "Policy",
                "value": "No recent decision" if not policy_decision else _humanize_decision_policy(policy_decision),
                "tone": "neutral" if not policy_decision else "info",
            },
            {
                "label": "Action",
                "value": "No action executed"
                if not policy_decision
                else ((policy_decision.get("action_plan") or {}).get("type") or "No action"),
                "tone": "neutral" if not policy_decision else "info",
            },
            {
                "label": "Verification",
                "value": verification_value,
                "tone": verification_tone,
            },
            {
                "label": "Replicas",
                "value": f"{replicas_ready} / {replicas_desired}",
                "tone": "success" if replicas_ready == replicas_desired and replicas_desired else "warning",
            },
        ]
    )

    return cards


def _build_stage(
    *,
    key: str,
    title: str,
    status: str,
    summary: str,
    last_updated: Optional[str] = None,
    evidence_source: Optional[str] = None,
    details: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "summary": summary,
        "lastUpdated": last_updated,
        "evidenceSource": evidence_source,
        "details": details or [],
    }


def build_pipeline_stages(
    *,
    system_state: Dict[str, Any],
    anomaly: Optional[Dict[str, Any]] = None,
    rca: Optional[Dict[str, Any]] = None,
    policy_decision: Optional[Dict[str, Any]] = None,
    verification: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    system = system_state.get("system", "unknown")
    is_odoo = system == "odoo"

    latency_value = system_state.get("latencyP95Ms")
    monitor_details = [
        {"label": "System", "value": _stringify(system_state.get("system"))},
        {"label": "Deployment", "value": _stringify(system_state.get("deployment"))},
        {"label": "Namespace", "value": _stringify(system_state.get("namespace"))},
        {"label": "Health", "value": _stringify(system_state.get("health")).title()},
        {"label": "Latency p95 (ms)", "value": _stringify(_safe_round(latency_value, 2))},
    ]

    if is_odoo:
        return [
            _build_stage(
                key="monitor",
                title="Monitor",
                status="Active",
                summary="Odoo KPIs are connected through ingress-backed monitoring.",
                evidence_source="Prometheus / ingress metrics",
                details=monitor_details,
            ),
            _build_stage(
                key="detect",
                title="Detect",
                status="Observed",
                summary="Odoo detect agent is connected to the SmartOps pipeline.",
                evidence_source="Odoo detect agent",
                details=[
                    {"label": "Profile", "value": "odoo"},
                    {"label": "State", "value": "Monitoring only"},
                    {"label": "Anomaly", "value": "No active anomaly" if not anomaly else "Anomaly detected"},
                ],
            ),
            _build_stage(
                key="diagnose",
                title="Diagnose",
                status="Idle" if not rca else "Available",
                summary="RCA skipped because there is no recent anomaly for Odoo."
                if not rca
                else "Recent diagnosis is available for Odoo.",
                evidence_source="Odoo diagnose agent",
                details=[
                    {"label": "Diagnosis state", "value": "RCA skipped" if not rca else "RCA available"},
                    {"label": "Reason", "value": "No recent anomaly" if not rca else "Recent anomaly available"},
                ],
            ),
            _build_stage(
                key="decide",
                title="Decide",
                status="Idle",
                summary="No action decision is needed while Odoo remains stable.",
                evidence_source="Policy engine",
                details=[
                    {"label": "Decision", "value": "No action"},
                    {"label": "Reason", "value": "Stable connected ERP plug-in"},
                ],
            ),
            _build_stage(
                key="act",
                title="Act",
                status="Idle",
                summary="Manual scenario actions are not exposed for Odoo.",
                evidence_source="Dashboard policy",
                details=[
                    {"label": "Action state", "value": "Hidden for Odoo"},
                    {"label": "Reason", "value": "Plug-in proof only"},
                ],
            ),
            _build_stage(
                key="verify",
                title="Verify",
                status="Idle",
                summary="Verification remains available later if needed.",
                evidence_source="Verification API",
                details=[
                    {"label": "Verification", "value": "Not required in current Odoo demo flow"},
                ],
            ),
        ]

    is_manual_policy = bool(
        policy_decision and str(policy_decision.get("policy", "")).startswith("manual_")
    )

    detect_status = "Idle"
    detect_summary = "No active anomaly currently detected for the selected system."
    detect_last_updated = None
    detect_details = [
        {"label": "Window ID", "value": "-"},
        {"label": "Anomaly type", "value": "None"},
        {"label": "Score", "value": "-"},
        {"label": "Risk", "value": "-"},
        {"label": "Profile", "value": system},
    ]

    if is_manual_policy:
        manual_action_type = ((policy_decision.get("action_plan") or {}).get("type")) if policy_decision else None
        detect_status = "Observed"
        detect_summary = "Manual action execution is being shown instead of anomaly-triggered detection."
        detect_last_updated = policy_decision.get("ts_utc") or policy_decision.get("ts") if policy_decision else None
        detect_details = [
            {"label": "Mode", "value": "Manual DevOps action"},
            {"label": "Trigger", "value": _stringify(manual_action_type, "manual")},
            {"label": "Anomaly source", "value": "Not applicable"},
            {"label": "Risk", "value": "Not applicable"},
            {"label": "Profile", "value": system},
        ]
    elif anomaly:
        detect_status = "Anomaly"
        detect_summary = f"Anomaly detected for window {anomaly.get('windowId', '-')}"
        detect_last_updated = anomaly.get("ts") or anomaly.get("ts_utc")
        detect_details = [
            {"label": "Window ID", "value": _stringify(anomaly.get("windowId"))},
            {"label": "Anomaly type", "value": _stringify(anomaly.get("type"), "Unknown")},
            {"label": "Score", "value": _stringify(_safe_round(anomaly.get("score"), 4))},
            {"label": "Risk", "value": _stringify((anomaly.get("metadata") or {}).get("risk"))},
            {"label": "Profile", "value": _stringify((anomaly.get("metadata") or {}).get("profile"), system)},
        ]

    diagnose_status = "Idle" if not rca else "Available"
    diagnose_summary = (
        "RCA will appear here when a recent anomaly is available."
        if not rca
        else f"Top RCA cause available for window {rca.get('windowId', '-')}"
    )
    diagnose_last_updated = None
    top_cause = (rca.get("rankedCauses") or [{}])[0] if rca else {}
    diagnose_details = [
        {"label": "Window ID", "value": "-"},
        {"label": "Top cause", "value": "No diagnosis available"},
        {"label": "Probability", "value": "-"},
        {"label": "Confidence", "value": "-"},
    ]

    if is_manual_policy:
        diagnose_status = "Not applicable"
        diagnose_summary = "RCA is not applicable for direct manual DevOps actions."
        diagnose_last_updated = policy_decision.get("ts_utc") or policy_decision.get("ts") if policy_decision else None
        diagnose_details = [
            {"label": "Diagnosis state", "value": "Not applicable"},
            {"label": "Reason", "value": "Direct manual action"},
            {"label": "Probability", "value": "-"},
            {"label": "Confidence", "value": "-"},
        ]
    elif rca:
        diagnose_last_updated = rca.get("ts") or rca.get("ts_utc")
        diagnose_details = [
            {"label": "Window ID", "value": _stringify(rca.get("windowId"))},
            {"label": "Top cause", "value": _stringify(top_cause.get("cause"), "Unknown cause")},
            {"label": "Probability", "value": _stringify(_safe_round(top_cause.get("probability"), 4))},
            {"label": "Confidence", "value": _stringify(_safe_round(rca.get("confidence"), 4))},
        ]

    decide_status = "Waiting"
    decide_summary = "Recent policy decisions and guardrail outcomes will appear here."
    decide_last_updated = None
    decide_details = [
        {"label": "Decision", "value": "No recent decision"},
        {"label": "Policy", "value": "-"},
        {"label": "Priority", "value": "-"},
        {"label": "Guardrail", "value": "-"},
    ]

    if policy_decision:
        decision_value = str(policy_decision.get("decision", "")).lower()

        if decision_value == "blocked":
            decide_status = "Blocked"
            decide_summary = (
                f"Policy {_humanize_decision_policy(policy_decision)} was blocked by guardrails."
            )
        else:
            decide_status = "Decision"
            decide_summary = (
                f"Policy {_humanize_decision_policy(policy_decision)} returned "
                f"{policy_decision.get('decision', '-')}"
            )

        decide_last_updated = policy_decision.get("ts_utc") or policy_decision.get("ts")
        decide_details = [
            {"label": "Decision", "value": _stringify(policy_decision.get("decision"))},
            {"label": "Policy", "value": _humanize_decision_policy(policy_decision)},
            {"label": "Priority", "value": _stringify(policy_decision.get("priority"))},
            {"label": "Guardrail", "value": _stringify(policy_decision.get("guardrail_reason"), "Allowed")},
        ]

    act_status = "Waiting"
    act_summary = "Action plans and execution results will appear here."
    act_details = [
        {"label": "Action type", "value": "No action"},
        {"label": "Target", "value": "-"},
        {"label": "Dry run", "value": "-"},
        {"label": "Verify", "value": "-"},
    ]

    if policy_decision and str(policy_decision.get("decision", "")).lower() == "blocked":
        act_status = "Blocked"
        act_summary = "No remediation was executed because guardrails blocked the action."
        act_details = [
            {"label": "Action state", "value": "Blocked before execution"},
            {"label": "Policy", "value": _humanize_decision_policy(policy_decision)},
            {"label": "Guardrail", "value": _stringify(policy_decision.get("guardrail_reason"), "-")},
            {"label": "Execution", "value": "Not executed"},
        ]
    elif policy_decision and policy_decision.get("action_plan"):
        action_plan = policy_decision.get("action_plan") or {}
        target = action_plan.get("target") or {}
        action_type = action_plan.get("type", "unknown")
        target_name = target.get("name") or "-"
        target_namespace = target.get("namespace") or "-"
        target_replicas = ((action_plan.get("scale") or {}).get("replicas"))
        act_status = "Planned"
        act_summary = f"Action plan prepared: {action_type}"
        act_details = [
            {"label": "Action type", "value": _stringify(action_type)},
            {"label": "Target", "value": f"{target_namespace}/{target_name}"},
            {"label": "Dry run", "value": _stringify(action_plan.get("dry_run"), "False")},
            {"label": "Verify", "value": _stringify(action_plan.get("verify"), "False")},
        ]
        if target_replicas is not None:
            act_details.append({"label": "Target replicas", "value": _stringify(target_replicas)})

    verify_status = "Idle"
    verify_summary = "Verification will appear after an action that requires execution checks."
    verify_details = [
        {"label": "Status", "value": "Not available"},
        {"label": "Overall", "value": "-"},
        {"label": "Ready replicas", "value": "-"},
        {"label": "Desired replicas", "value": "-"},
    ]

    if policy_decision and ((policy_decision.get("action_plan") or {}).get("verify")) and not verification:
        verify_status = "Waiting"
        verify_summary = "Verification is waiting to start after action execution."
        verify_details = [
            {"label": "Status", "value": "Waiting"},
            {"label": "Overall", "value": "-"},
            {"label": "Ready replicas", "value": "-"},
            {"label": "Desired replicas", "value": "-"},
        ]

    if policy_decision and str(policy_decision.get("decision", "")).lower() == "blocked":
        verify_status = "Blocked"
        verify_summary = "Verification was not required because no action was executed."
        verify_details = [
            {"label": "Status", "value": "Blocked"},
            {"label": "Overall", "value": "Not applicable"},
            {"label": "Ready replicas", "value": _stringify(system_state.get("replicasReady"))},
            {"label": "Desired replicas", "value": _stringify(system_state.get("replicasDesired"))},
            {"label": "Message", "value": "Guardrails prevented execution, so verification was skipped."},
        ]
    elif verification:
        verification_state = verification.get("status")
        overall = verification.get("overall")

        if verification_state == "pending" or overall is None:
            verify_status = "Pending"
            verify_summary = "Verification is pending after action execution."
        elif overall is True:
            verify_status = "Passed"
            verify_summary = "Verification checks completed successfully."
        else:
            verify_status = "Failed"
            verify_summary = "Verification checks completed with failures."

        verify_details = [
            {"label": "Status", "value": _stringify(verification.get("status"), "unknown").title()},
            {"label": "Overall", "value": "Passed" if overall is True else "Failed" if overall is False else "Pending"},
            {"label": "Ready replicas", "value": _stringify(verification.get("ready_replicas"))},
            {"label": "Desired replicas", "value": _stringify(verification.get("desired_replicas"))},
        ]
        if verification.get("message"):
            verify_details.append({"label": "Message", "value": _stringify(verification.get("message"))})

    return [
        _build_stage(
            key="monitor",
            title="Monitor",
            status="Active",
            summary="Metrics flowing from live Kubernetes and Prometheus sources.",
            evidence_source="Prometheus / service metrics",
            details=monitor_details,
        ),
        _build_stage(
            key="detect",
            title="Detect",
            status=detect_status,
            summary=detect_summary,
            last_updated=detect_last_updated,
            evidence_source="Recent anomaly signals",
            details=detect_details,
        ),
        _build_stage(
            key="diagnose",
            title="Diagnose",
            status=diagnose_status,
            summary=diagnose_summary,
            last_updated=diagnose_last_updated,
            evidence_source="Recent RCA signals",
            details=diagnose_details,
        ),
        _build_stage(
            key="decide",
            title="Decide",
            status=decide_status,
            summary=decide_summary,
            last_updated=decide_last_updated,
            evidence_source="Policy audit / policy engine",
            details=decide_details,
        ),
        _build_stage(
            key="act",
            title="Act",
            status=act_status,
            summary=act_summary,
            last_updated=decide_last_updated,
            evidence_source="Action plan / orchestrator",
            details=act_details,
        ),
        _build_stage(
            key="verify",
            title="Verify",
            status=verify_status,
            summary=verify_summary,
            evidence_source="Verification API",
            details=verify_details,
        ),
    ]
