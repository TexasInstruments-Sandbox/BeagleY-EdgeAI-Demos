import { useEffect, useMemo, useRef, useState } from "react";
import { changeSource, control, fetchStatus, PREVIEW_STATUS, saveSpots, uploadVideo } from "./api";

const duration = (seconds = 0) => {
  const value = Math.max(0, Math.round(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${minutes}m ${String(secs).padStart(2, "0")}s`;
};
const clock = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "LIVE";
const size = (bytes = 0) => `${(bytes / (1024 ** 3)).toFixed(1)} GB`;
const points = (polygon) => polygon.map(([x, y]) => `${x * 1000},${y * 562}`).join(" ");

function Mark() {
  return <svg viewBox="0 0 52 52" aria-hidden="true"><path d="M24 4 9 28h14l-3 20 23-29H28l5-15Z" /><path d="M5 44h42M6 36h8m24 0h8" /></svg>;
}

function SourceDialog({ busy, onClose, run }) {
  const [path, setPath] = useState("/usr/share/ti-edgeai-ev-spot-sentinel/ev-spot-demo.mp4");
  const [progress, setProgress] = useState(0);
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="modal source-modal">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <span className="eyebrow">Input router</span><h2>Choose a vision source</h2>
      <p>Both inputs feed the same occupancy, ALPR, and dwell pipeline. Camera mode uses CSI0 and the TI VPAC ISP.</p>
      <button className="camera-card" disabled={busy} onClick={() => run(() => changeSource("camera"), "Switching to IMX219 · CSI0")}>IMX219 · CSI0 <small>VPAC VISS hardware ISP · 1920 × 1080</small></button>
      <form onSubmit={(event) => { event.preventDefault(); run(() => changeSource("video", path), "Opening board video"); }}>
        <label>Existing board video</label><div><input value={path} onChange={(event) => setPath(event.target.value)} /><button disabled={busy}>Open</button></div>
      </form>
      <label className="upload">Upload from this browser<input type="file" accept="video/*" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) run(() => uploadVideo(file, setProgress), "Video uploaded and selected"); }} /></label>
      {progress > 0 && progress < 1 && <div className="progress"><i style={{ width: `${progress * 100}%` }} /></div>}
    </section>
  </div>;
}

function ZoneEditor({ spots, busy, onClose, onSave }) {
  const [draft, setDraft] = useState(() => spots.map((spot) => ({
    id: spot.id, name: spot.name, polygon: spot.polygon.map((point) => [...point]),
  })));
  const [drag, setDrag] = useState(null);
  const svg = useRef(null);
  const move = (event) => {
    if (!drag || !svg.current) return;
    const rect = svg.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    setDraft((value) => value.map((spot, spotIndex) => spotIndex !== drag.spot ? spot : { ...spot, polygon: spot.polygon.map((point, pointIndex) => pointIndex === drag.point ? [x, y] : point) }));
  };
  return <div className="modal-backdrop"><section className="modal zone-modal">
    <button className="close" onClick={onClose}>×</button><span className="eyebrow">Perspective map</span><h2>Calibrate parking zones</h2>
    <p>Drag each vertex onto the painted edges of its parking space. The vehicle’s lower-center point determines occupancy.</p>
    <div className="zone-canvas">
      <img src="/demo-parking.png" alt="Parking zone reference" />
      <svg ref={svg} viewBox="0 0 1000 562" onPointerMove={move} onPointerUp={() => setDrag(null)} onPointerLeave={() => setDrag(null)}>
        {draft.map((spot, spotIndex) => <g key={spot.id}><polygon points={points(spot.polygon)} className={`zone zone-${spotIndex}`} /><text x={spot.polygon[0][0] * 1000 + 12} y={spot.polygon[0][1] * 562 + 28}>{spot.name}</text>{spot.polygon.map(([x, y], pointIndex) => <circle key={pointIndex} cx={x * 1000} cy={y * 562} r="11" onPointerDown={(event) => { event.currentTarget.setPointerCapture?.(event.pointerId); setDrag({ spot: spotIndex, point: pointIndex }); }} />)}</g>)}
      </svg>
    </div><div className="modal-actions"><button onClick={onClose}>Cancel</button><button className="primary" disabled={busy} onClick={() => onSave(draft)}>Save zones</button></div>
  </section></div>;
}

function Viewport({ status, preview, editing, onEdit }) {
  return <section className="viewport-panel panel">
    <div className="panel-title"><div><span className="eyebrow">Live overview</span><strong>{status.source.label}</strong></div><button onClick={onEdit}>{editing ? "Editing zones" : "Edit zones"}</button></div>
    <div className="viewport">
      <img src={preview ? "/demo-parking.png" : "/stream.mjpg"} alt="Live parking area" />
      <svg viewBox="0 0 1000 562" preserveAspectRatio="none" aria-hidden="true">
        {status.spots.map((spot, index) => <g key={spot.id}><polygon points={points(spot.polygon)} className={`zone zone-${spot.state.toLowerCase()} zone-${index}`} /><text x={spot.polygon[0][0] * 1000 + 12} y={spot.polygon[0][1] * 562 + 26}>{spot.name} · {spot.state}</text></g>)}
      </svg>
      {status.spots.map((spot) => spot.vehicle?.box && <div key={`${spot.id}-vehicle`} className={`object-box ${spot.overstay ? "overstay" : ""}`} style={{ left: `${spot.vehicle.box.left * 100}%`, top: `${spot.vehicle.box.top * 100}%`, width: `${spot.vehicle.box.width * 100}%`, height: `${spot.vehicle.box.height * 100}%` }}><b>{spot.vehicle.label} · {(spot.vehicle.score * 100).toFixed(0)}%</b></div>)}
      {status.spots.map((spot) => spot.plate?.box && <div key={`${spot.id}-plate`} className="plate-box" style={{ left: `${spot.plate.box.left * 100}%`, top: `${spot.plate.box.top * 100}%`, width: `${spot.plate.box.width * 100}%`, height: `${spot.plate.box.height * 100}%` }}><b>{spot.plate.text}</b></div>)}
      <div className="live-chip"><i /> LIVE · {status.source.type === "camera" ? "VPAC ISP" : "VIDEO"}</div>
      {status.paused && <div className="veil">Pipeline paused</div>}
      {status.error && <div className="veil error">{status.error}</div>}
    </div>
  </section>;
}

function SpotRail({ status }) {
  const overstay = status.spots.find((spot) => spot.overstay);
  return <aside className="spot-rail panel"><div className="panel-title"><div><span className="eyebrow">EV zone state</span><strong>{status.spots.filter((spot) => !spot.occupied).length} available</strong></div></div>
    <div className="spot-list">{status.spots.map((spot) => <article className={`spot-card state-${spot.state.toLowerCase()}`} key={spot.id}>
      <div><span>{spot.name}</span><b>{spot.state}</b></div><strong>{spot.occupied ? duration(spot.dwell_seconds) : "READY"}</strong>
      <small>{spot.plate?.text || (spot.occupied ? "Plate pending · no guesses" : "Waiting for vehicle")}</small>
    </article>)}</div>
    {overstay && <div className="alert"><span>Overstay alert</span><strong>{overstay.plate?.text || "UNIDENTIFIED"}</strong><small>{overstay.name} · {duration(overstay.dwell_seconds - status.policy.overstay_seconds)} over policy</small></div>}
  </aside>;
}

function Telemetry({ status }) {
  const used = status.memory.used_bytes / Math.max(1, status.memory.total_bytes) * 100;
  return <aside className="telemetry panel">
    <div><span className="eyebrow">Accelerator</span><strong className="good"><i /> {status.acceleration.label}</strong><small>Vehicle · C7x-{status.acceleration.vehicle.core}<br />{status.acceleration.vehicle.nodes} / 283 graph nodes</small></div>
    <div><span className="eyebrow">ALPR</span><strong>GLOBAL OCR</strong><small>CPU EP · declared mixed pipeline<br />{status.acceleration.plate.invocations} reads</small></div>
    <div><span className="eyebrow">Video</span><strong>{status.source.isp_active ? "VPAC VISS" : "DECODE"}</strong><small>{status.source.isp_active ? "IMX219 CSI0 hardware ISP" : "File input"}</small></div>
    <div><span className="eyebrow">Performance</span><strong>{status.performance.fps.toFixed(1)} FPS</strong><small>TIDL {status.performance.vehicle_inference_ms.toFixed(0)} ms · E2E {status.performance.end_to_end_ms.toFixed(0)} ms</small></div>
    <div><span className="eyebrow">Memory</span><strong>{size(status.memory.used_bytes)} / {size(status.memory.total_bytes)}</strong><div className="meter"><i style={{ width: `${used}%` }} /></div><small>Service RSS {Math.round(status.memory.process_rss_bytes / 1048576)} MB</small></div>
    <div><span className="eyebrow">Privacy</span><strong>LOCAL ONLY</strong><small>{status.policy.retention_days}-day retention<br />Human review required</small></div>
  </aside>;
}

function Sessions({ status }) {
  return <section className="sessions panel"><div className="panel-title"><div><span className="eyebrow">Audit trail</span><strong>Recent parking sessions</strong></div><span>SQLite · local</span></div>
    <div className="table-scroll"><table><thead><tr><th>Plate</th><th>Spot</th><th>Arrived</th><th>Dwell</th><th>Status</th><th>Confidence</th></tr></thead><tbody>{status.recent_sessions.slice(0, 7).map((row) => <tr key={`${row.id}-${row.spot_id}`}><td><b>{row.plate || "UNIDENTIFIED"}</b></td><td>{row.spot_id}</td><td>{clock(row.started_utc)}</td><td>{duration(row.duration_seconds)}</td><td><span className={`pill ${row.overstay ? "amber" : ""}`}>{row.ended_utc ? "DEPARTED" : (row.overstay ? "OVERSTAY" : "ACTIVE")}</span></td><td>{row.plate_confidence ? `${(row.plate_confidence * 100).toFixed(0)}%` : "—"}</td></tr>)}</tbody></table></div>
  </section>;
}

function Leaderboard({ status }) {
  return <section className="leaderboard panel"><div className="panel-title"><div><span className="eyebrow">Dwell leaderboard</span><strong>Longest total stay</strong></div></div>
    <ol>{status.leaderboard.slice(0, 6).map((row, index) => <li key={row.plate}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{row.plate}</strong><small>{row.visits} visit{row.visits === 1 ? "" : "s"}{row.active ? " · active" : ""}</small></div><b>{duration(row.total_seconds)}</b></li>)}</ol>
    {!status.leaderboard.length && <p className="empty">A confirmed plate appears after two matching reads.</p>}
  </section>;
}

export default function App() {
  const preview = useMemo(() => new URLSearchParams(window.location.search).has("preview"), []);
  const snapshot = useMemo(() => new URLSearchParams(window.location.search).has("snapshot"), []);
  const [status, setStatus] = useState(PREVIEW_STATUS);
  const [connected, setConnected] = useState(preview);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [zonesOpen, setZonesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (preview) return undefined;
    let alive = true; let timer;
    const update = async () => { try { const value = await fetchStatus(); if (!alive) return; setStatus(value); setConnected(true); } catch { if (alive) setConnected(false); } finally { if (alive && !snapshot) timer = window.setTimeout(update, 750); } };
    update(); return () => { alive = false; clearTimeout(timer); };
  }, [preview, snapshot]);
  const run = async (operation, success) => {
    if (preview) { setMessage("Preview mode — connect to a BeagleY-AI to control the pipeline."); return; }
    setBusy(true); try { await operation(); setMessage(success); setSourceOpen(false); setZonesOpen(false); } catch (error) { setMessage(error.message); } finally { setBusy(false); window.setTimeout(() => setMessage(""), 5000); }
  };
  const saveZones = async (value) => {
    await control("pause");
    try { await saveSpots(value); }
    finally { await control("resume"); }
  };
  const occupied = status.spots.filter((spot) => spot.occupied).length;
  return <main className="shell">
    <header><div className="brand"><Mark /><div><h1>EV Spot Sentinel</h1><p>Occupancy · plate intelligence · dwell accountability</p></div></div><div className="header-actions"><span className={`health ${connected ? "" : "bad"}`}><i /> {connected ? "SYSTEM HEALTHY" : "RECONNECTING"}</span><div className="source-toggle"><button className={status.source.type === "camera" ? "active" : ""} onClick={() => run(() => changeSource("camera"), "Switching to IMX219 · CSI0")}>Camera</button><button className={status.source.type === "video" ? "active" : ""} onClick={() => setSourceOpen(true)}>Video</button></div><button onClick={() => run(() => control("capture"), "Proof frame and JSON saved")}>Record proof</button><button onClick={() => setZonesOpen(true)}>Settings</button></div></header>
    <section className="summary"><span><i className="available" /> {status.spots.length - occupied} available</span><span><i className="occupied" /> {occupied} occupied</span><span><i className="overstay" /> {status.spots.filter((spot) => spot.overstay).length} overstay</span><b>{status.source.label}</b></section>
    {!connected && !preview && <div className="connection">Waiting for EV Spot Sentinel on the board…</div>}
    <div className="top-grid"><Viewport status={status} preview={preview} editing={zonesOpen} onEdit={() => setZonesOpen(true)} /><SpotRail status={status} /><Telemetry status={status} /></div>
    <div className="bottom-grid"><Sessions status={status} /><Leaderboard status={status} /></div>
    <footer><span>BeagleY-AI · AM67A/J722S · PSDK 11.02</span><span>Vehicle occupancy accelerated · ALPR CPU clearly attributed</span><span>No cloud · no automated enforcement</span></footer>
    {sourceOpen ? <SourceDialog busy={busy} onClose={() => setSourceOpen(false)} run={run} /> : null}
    {zonesOpen ? <ZoneEditor spots={status.spots} busy={busy} onClose={() => setZonesOpen(false)} onSave={(value) => run(() => saveZones(value), "Parking zones saved")} /> : null}
    {message && <div className="toast">{message}</div>}
  </main>;
}
