import asyncio

from services.closed_loop import closed_loop_manager
from models.signal_models import AnomalySignal, AnomalyType

async def main():
    print("\n=== SmartOps Closed-Loop Manual Test ===\n")

    # Corrected valid signal (all required fields included)
    signal = AnomalySignal(
        windowId="win-001",
        service="erp-simulator",        # friendly name
        isAnomaly=True,                 # required
        score=0.92,                     # required
        type=AnomalyType.RESOURCE,      # resource anomaly → SCALE +1
        metadata={"source": "manual-test"}
    )

    print("Enqueuing anomaly signal...")
    await closed_loop_manager.enqueue_anomaly(signal)

    print("Waiting for closed-loop worker to process...")
    await asyncio.sleep(15)

    print("\nTest complete.\n")

asyncio.run(main())
