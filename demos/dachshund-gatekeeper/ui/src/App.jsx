import { useEffect, useMemo, useState } from "react";
import { changeSource, control, fetchStatus, PREVIEW_STATUS, uploadVideo } from "./api";
import { Header } from "./components/Header";
import { LiveViewport } from "./components/LiveViewport";
import { DecisionRail } from "./components/DecisionRail";
import { TelemetryStrip } from "./components/TelemetryStrip";
import { EventTimeline } from "./components/EventTimeline";
import { SourceDialog } from "./components/SourceDialog";

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
    let timer = null;
    const update = async () => {
      try {
        const value = await fetchStatus();
        if (!alive) return;
        setStatus(value);
        setConnected(true);
        if (!snapshot) timer = window.setTimeout(update, 750);
      } catch {
        if (!alive) return;
        setConnected(false);
        timer = window.setTimeout(update, 750);
      }
    };
    update();
    return () => { alive = false; if (timer !== null) window.clearTimeout(timer); };
  }, [preview, snapshot]);

  const run = async (operation, success) => {
    if (preview) { setMessage("Preview mode — connect to a running BeagleY-AI to control the pipeline."); return; }
    setBusy(true);
    try { await operation(); setMessage(success); setDialog(false); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); window.setTimeout(() => setMessage(""), 5000); }
  };

  return (
    <main className="app-shell">
      <Header
        sourceType={status.source.type}
        onCamera={() => run(() => changeSource("camera"), "Switching to IMX219 · CSI0")}
        onVideo={() => setDialog(true)}
      />
      {!connected && !preview && <div className="connection-banner">Waiting for the Gatekeeper service…</div>}
      <div className="primary-grid">
        <LiveViewport status={status} preview={preview} snapshot={snapshot} />
        <DecisionRail status={status} onChangeSource={() => setDialog(true)} />
      </div>
      <TelemetryStrip status={status} />
      <EventTimeline
        status={status}
        busy={busy}
        onPause={() => run(() => control(status.paused ? "resume" : "pause"), status.paused ? "Pipeline resumed" : "Pipeline paused")}
        onCapture={() => run(() => control("capture"), "Proof image and JSON saved on the board")}
      />
      <footer><span>BeagleY-AI · AM67A/J722S</span><span>Detector C7x-1 · Breed C7x-2</span><span>All inference local</span></footer>
      <SourceDialog
        open={dialog} busy={busy} onClose={() => setDialog(false)}
        onCamera={() => run(() => changeSource("camera"), "Switching to IMX219 · CSI0")}
        onPath={(path) => run(() => changeSource("video", path), "Opening board video")}
        onUpload={(file, onProgress) => run(() => uploadVideo(file, onProgress), "Video uploaded and selected")}
      />
      {message && <div className="toast" role="status">{message}</div>}
    </main>
  );
}
