from collections import deque
from typing import Deque, Tuple, List

from ..models.signal_models import AnomalySignal, RcaSignal

_MAX_SIGNALS = 200

_anomalies: Deque[AnomalySignal] = deque(maxlen=_MAX_SIGNALS)
_rcas: Deque[RcaSignal] = deque(maxlen=_MAX_SIGNALS)


def add_anomaly(signal: AnomalySignal) -> None:
    _anomalies.append(signal)


def add_rca(signal: RcaSignal) -> None:
    _rcas.append(signal)


def get_recent_signals(limit: int = 20) -> Tuple[List[AnomalySignal], List[RcaSignal]]:
    anomalies = list(_anomalies)[-limit:]
    rcas = list(_rcas)[-limit:]
    return anomalies, rcas
