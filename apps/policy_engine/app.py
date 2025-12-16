from typing import Union

from fastapi import FastAPI

from apps.policy_engine.schemas.models import (
    AnomalySignal,
    RcaSignal,
    ActionPlan,
)
from apps.policy_engine.runtime.evaluator import evaluate_signal_with_policies

app = FastAPI(title="SmartOps Policy Engine", version="0.2.0")


@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "policy-engine"}


@app.post("/v1/policy/evaluate", response_model=ActionPlan)
def evaluate_policy(signal: Union[AnomalySignal, RcaSignal]):
    return evaluate_signal_with_policies(signal)
