export function LiveViewport({ status, preview, snapshot }) {
  const box = status.detection?.box_normalized;
  const breed = status.breed;
  const style = box ? {
    left: `${box.left * 100}%`, top: `${box.top * 100}%`,
    width: `${box.width * 100}%`, height: `${box.height * 100}%`,
  } : undefined;
  return (
    <section className="live-viewport" aria-label="Live annotated inference">
      <img
        src={preview ? "/demo-dachshund.jpg" : (
          snapshot ? "/frame.jpg?snapshot=1" : `/frame.jpg?sequence=${status.performance.frames}`
        )}
        alt={preview ? "Dachshund sample used for UI preview" : "Live Gatekeeper camera or video stream"}
      />
      <div className="live-source"><i />LIVE · {status.source.label}</div>
      {box && (
        <div className="detection-box" style={style}>
          <div className="detection-label">
            {breed.label} <strong>{Math.round((breed.score || 0) * 1000) / 10}%</strong>
          </div>
        </div>
      )}
      {status.paused && <div className="paused-overlay">Paused</div>}
      {status.error && <div className="stream-error">{status.error}</div>}
    </section>
  );
}
