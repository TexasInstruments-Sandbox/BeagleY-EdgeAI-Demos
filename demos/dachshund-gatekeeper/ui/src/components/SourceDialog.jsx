import { useState } from "react";
import { CloseIcon } from "../icons";

export function SourceDialog({ open, onClose, onCamera, onPath, onUpload, busy }) {
  const [path, setPath] = useState("");
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="source-dialog" role="dialog" aria-modal="true" aria-labelledby="source-title">
        <button className="dialog-close" onClick={onClose} aria-label="Close"><CloseIcon /></button>
        <h2 id="source-title">Choose a source</h2>
        <p>Use the live CSI0 sensor, a video already on the board, or upload one from this browser.</p>
        <div className="source-options">
          <button className="camera-option" onClick={onCamera} disabled={busy}><strong>IMX219 · CSI0</strong><span>Raw Bayer through TI VPAC ISP</span></button>
          <form onSubmit={(event) => { event.preventDefault(); onPath(path); }}>
            <label htmlFor="video-path">Existing board path</label>
            <div><input id="video-path" value={path} onChange={(event) => setPath(event.target.value)} placeholder="/home/andrei/dachshund.mp4" /><button disabled={!path || busy}>Open</button></div>
          </form>
          <form onSubmit={(event) => { event.preventDefault(); onUpload(file, setProgress); }}>
            <label htmlFor="video-upload">Upload a video</label>
            <div><input id="video-upload" type="file" accept="video/*,.h264,.h265" onChange={(event) => setFile(event.target.files?.[0] || null)} /><button disabled={!file || busy}>Upload</button></div>
            {progress > 0 && progress < 1 && <div className="upload-progress"><i style={{ width: `${progress * 100}%` }} /></div>}
          </form>
        </div>
      </section>
    </div>
  );
}
