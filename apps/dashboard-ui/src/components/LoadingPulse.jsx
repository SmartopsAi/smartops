const STEPS = ["Detecting", "Diagnosing", "Deciding", "Acting", "Verifying"];

function LoadingPulse({ activeLabel = "Closed-loop run in progress" }) {
  return (
    <div className="loading-pulse" role="status" aria-live="polite">
      <div className="loading-pulse__track">
        {STEPS.map((step, index) => (
          <span key={step} className="loading-pulse__step" style={{ "--pulse-index": index }}>
            <span className="loading-pulse__dot" />
            {step}
          </span>
        ))}
      </div>
      <p>{activeLabel}</p>
    </div>
  );
}

export default LoadingPulse;
