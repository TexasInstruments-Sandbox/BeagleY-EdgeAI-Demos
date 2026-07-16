import { useEffect, useMemo, useState } from "react";
import { changeSource, control, fetchStatus, PREVIEW_STATUS, uploadMedia } from "./api";

const formatName = (value) => ({ QRCode: "QR CODE", DataMatrix: "DATA MATRIX", Code128: "CODE 128", EAN13: "EAN-13" }[value] || value || "CODE");
const metric = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : "—";
const megabytes = (value) => `${metric((value || 0) / 1024 ** 2, 0)} MB`;
const clock = (value) => value ? new Date(value).toLocaleTimeString([], { hour12: false }) : "—";

function Icon({ name }) {
  const paths = {
    source: <><path d="M5 7h14M5 12h14M5 17h14"/><circle cx="8" cy="7" r="1.5"/><circle cx="16" cy="12" r="1.5"/><circle cx="10" cy="17" r="1.5"/></>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    play: <path d="m8 5 11 7-11 7Z"/>,
    clear: <><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13"/></>,
    copy: <><rect x="8" y="8" width="11" height="11" rx="1"/><path d="M16 8V5H5v11h3"/></>,
    camera: <><path d="M4 8h4l2-3h4l2 3h4v11H4Z"/><circle cx="12" cy="13" r="3"/></>,
    capture: <><path d="M5 5h4M5 5v4M19 5h-4M19 5v4M5 19h4M5 19v-4M19 19h-4M19 19v-4"/><circle cx="12" cy="12" r="3"/></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function Header({ status, busy, onSource, onControl }) {
  return <header className="header">
    <div className="brand"><i className="brand-mark"/><div><h1>OmniCode</h1><p>Accelerated multi-format reader</p></div></div>
    <div className="source-readout"><span>LIVE SOURCE</span><strong><i/>{status.source.label}</strong></div>
    <nav aria-label="Pipeline controls">
      <button onClick={onSource}><Icon name="source"/>Source</button>
      <button disabled={busy} onClick={() => onControl(status.paused ? "resume" : "pause")}><Icon name={status.paused ? "play" : "pause"}/>{status.paused ? "Resume" : "Pause"}</button>
      <button disabled={busy} onClick={() => onControl("clear")}><Icon name="clear"/>Clear</button>
    </nav>
  </header>;
}

function Viewport({ status, preview }) {
  return <section className={`viewport ${preview ? "preview-scene" : ""}`} aria-label="Live code detections">
    {!preview && <img src="/stream.mjpg" alt="Live OmniCode camera or media stream"/>}
    {status.detections.map((box, index) => <div key={`${index}-${box.left}`} className={`code-box ${box.decoded ? "decoded" : "pending"}`} style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}><span>{box.decoded ? "CODE" : "DETECTED"} · {metric(box.score * 100, 1)}%</span></div>)}
    <div className="viewport-status"><i/>{status.paused ? "PAUSED" : "LIVE"} · {status.source.label}</div>
    {status.error && <div className="stream-error">{status.error}</div>}
  </section>;
}

function ResultRail({ status, onCopy }) {
  const selected = status.selected;
  return <aside className="result-rail">
    <section className="selected-result"><h2>SELECTED RESULT</h2>
      {selected ? <><div className="format-row"><strong>{formatName(selected.format)}</strong><span>{metric(selected.detector_score * 100, 1)}%</span></div><pre>{selected.text}</pre><dl><div><dt>TYPE</dt><dd>{selected.content_type}</dd></div><div><dt>SEEN</dt><dd>{selected.count}×</dd></div><div><dt>DECODE</dt><dd>{metric(selected.decode_ms)} ms</dd></div><div><dt>TIME</dt><dd>{clock(selected.timestamp)}</dd></div></dl><button className="copy-action" onClick={() => onCopy(selected.text)}><Icon name="copy"/>Copy payload</button></> : <div className="empty">Point the camera at a supported code.</div>}
    </section>
    <section className="recent"><div className="section-heading"><h2>RECENT SCANS</h2><span>{status.scans.length} UNIQUE</span></div><div className="scan-list">
      {status.scans.map((scan) => <article className={selected?.id === scan.id ? "active" : ""} key={scan.id}><div><strong>{formatName(scan.format)}</strong><time>{clock(scan.timestamp)}</time></div><p>{scan.text}</p><span>{metric(scan.detector_score * 100, 0)}% · {scan.count}×</span></article>)}
      {!status.scans.length && <div className="empty">No decoded payloads yet.</div>}
    </div></section>
  </aside>;
}

function Telemetry({ status, onCapture }) {
  const acceleration = status.acceleration;
  const isp = status.source.isp_active;
  const memoryPercent = (status.memory.used_bytes / status.memory.total_bytes) * 100 || 0;
  return <section className="telemetry" aria-label="Runtime telemetry">
    <div className="pipeline"><h2>ACCELERATED PIPELINE</h2><div><span><i/>CSI / FILE</span><b/><span><i/>VPAC ISP</span><b/><span><i/>TIDL C7x/MMA</span><b/><span className="cpu-stage"><i/>ZXING CPU ROI</span></div></div>
    <div className="metric accent"><strong>{metric(status.performance.fps)} FPS</strong><span>THROUGHPUT</span></div>
    <div className="metric"><strong>{metric(status.performance.detector_ms)} ms</strong><span>DETECT · C7x</span></div>
    <div className="metric"><strong>{metric(status.performance.decoder_ms)} ms</strong><span>DECODE AVG · CPU ROI</span></div>
    <div className={`metric ${isp ? "accent" : ""}`}><strong>{isp ? "ACTIVE" : "BYPASSED"}</strong><span>VPAC ISP</span></div>
    <div className="metric accent"><strong>{acceleration.cpu_fallback}</strong><span>CPU FALLBACK</span></div>
    <div className="metric"><strong>{metric(status.system.cpu_percent)}%</strong><span>SYSTEM CPU</span></div>
    <div className="memory"><strong>{megabytes(status.memory.process_rss_bytes)} RSS</strong><span>{megabytes(status.memory.available_bytes)} AVAILABLE</span><i><b style={{ width: `${Math.min(100, memoryPercent)}%` }}/></i></div>
    <button className="proof" onClick={onCapture}><Icon name="capture"/><span>Save proof</span></button>
  </section>;
}

function SourceDialog({ open, busy, onClose, onCamera, onPath, onUpload }) {
  const [path, setPath] = useState("");
  const [progress, setProgress] = useState(0);
  if (!open) return null;
  return <div className="dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="source-title"><div><h2 id="source-title">SELECT INPUT</h2><button aria-label="Close" onClick={onClose}>×</button></div><button className="camera-choice" disabled={busy} onClick={onCamera}><Icon name="camera"/><span><strong>IMX219 · CSI0</strong><small>TI VPAC ISP · 1920 × 1080</small></span></button><label>BOARD PATH<input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/home/user/video.mp4 or image.png"/></label><button disabled={busy || !path} onClick={() => onPath(path)}>Open board media</button><label className="upload">UPLOAD IMAGE OR VIDEO<input type="file" accept="image/*,video/*" onChange={(event) => event.target.files[0] && onUpload(event.target.files[0], setProgress)}/><span>{progress ? `Uploading ${Math.round(progress * 100)}%` : "Choose a file from this device"}</span></label></section></div>;
}

export default function App() {
  const preview = useMemo(() => new URLSearchParams(window.location.search).has("preview"), []);
  const snapshot = useMemo(() => new URLSearchParams(window.location.search).has("snapshot"), []);
  const [status, setStatus] = useState(PREVIEW_STATUS);
  const [connected, setConnected] = useState(preview);
  const [dialog, setDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (preview) return undefined;
    let alive = true;
    let timer;
    const update = async () => {
      try { const value = await fetchStatus(); if (!alive) return; setStatus(value); setConnected(true); }
      catch { if (!alive) return; setConnected(false); }
      if (!snapshot) timer = window.setTimeout(update, 700);
    };
    update();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [preview, snapshot]);

  const run = async (operation, success) => {
    if (preview) { setMessage("Preview mode — connect to a BeagleY-AI to control the pipeline."); return; }
    setBusy(true);
    try { await operation(); setMessage(success); setDialog(false); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); window.setTimeout(() => setMessage(""), 4500); }
  };

  const copy = async (payload) => {
    try { await navigator.clipboard.writeText(payload); setMessage("Payload copied — it was not opened or executed."); }
    catch { setMessage("Clipboard access was not available."); }
    window.setTimeout(() => setMessage(""), 3500);
  };

  return <main className="app-shell">
    <Header status={status} busy={busy} onSource={() => setDialog(true)} onControl={(action) => run(() => control(action), `${action[0].toUpperCase()}${action.slice(1)} complete`)} />
    {!connected && !preview && <div className="connection-banner">Waiting for the OmniCode service…</div>}
    <div className="primary-grid"><Viewport status={status} preview={preview}/><ResultRail status={status} onCopy={copy}/></div>
    <Telemetry status={status} onCapture={() => run(() => control("capture"), "Proof image and JSON saved on the board")}/>
    <footer><span>BeagleY-AI · AM67A/J722S</span><span>{status.acceleration.detector.provider} · {status.acceleration.detector.nodes} nodes · C7x-{status.acceleration.detector.core}</span><span>Decode only · never auto-open</span></footer>
    <SourceDialog open={dialog} busy={busy} onClose={() => setDialog(false)} onCamera={() => run(() => changeSource("camera"), "Switching to IMX219 · CSI0")} onPath={(path) => run(() => changeSource("media", path), "Opening board media")} onUpload={(file, progress) => run(() => uploadMedia(file, progress), "Media uploaded and selected")}/>
    {message && <div className="toast" role="status">{message}</div>}
  </main>;
}
