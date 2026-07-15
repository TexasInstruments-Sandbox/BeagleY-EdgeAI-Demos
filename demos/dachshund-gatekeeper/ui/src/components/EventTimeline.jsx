import { CameraIcon, GateIcon, PauseIcon } from "../icons";

const displayTime = (timestamp) => {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export function EventTimeline({ status, onPause, onCapture, busy }) {
  const events = status.events || [];
  return (
    <section className="activity-band">
      <div className="event-timeline">
        <h2>Event timeline</h2>
        <div className="event-list">
          {events.length === 0 && <div className="empty-event">Waiting for a stable dog track…</div>}
          {events.map((event, index) => (
            <div className={`event-row ${index === 0 ? "selected" : ""} event-${event.state.toLowerCase()}`} key={`${event.timestamp}-${event.title}`}>
              <time>{displayTime(event.timestamp)}</time>
              <GateIcon locked={event.state !== "AUTHORIZED"} />
              <span>{event.title}</span>
              <strong>{event.confidence == null ? "" : `${(event.confidence * 100).toFixed(1)}%`}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="actions-panel">
        <div className="action-buttons">
          <button onClick={onPause} disabled={busy}><PauseIcon paused={status.paused} />{status.paused ? "Resume" : "Pause"}</button>
          <button onClick={onCapture} disabled={busy}><CameraIcon />Capture proof</button>
        </div>
        <div className="system-health"><span>System health</span><i className={status.error ? "bad" : ""} /><strong>{status.error ? "FAULT" : "OK"}</strong><span>Uptime</span><b>{formatDuration(status.uptime_seconds)}</b></div>
      </div>
    </section>
  );
}

function formatDuration(seconds = 0) {
  const hours = Math.floor(seconds / 3600).toString().padStart(2, "0");
  const minutes = Math.floor(seconds % 3600 / 60).toString().padStart(2, "0");
  const secs = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${hours}:${minutes}:${secs}`;
}
