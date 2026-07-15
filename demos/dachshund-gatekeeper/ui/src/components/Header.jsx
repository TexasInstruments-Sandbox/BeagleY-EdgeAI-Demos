import { BrandMark } from "../icons";

export function Header({ sourceType, onCamera, onVideo }) {
  return (
    <header className="header">
      <div className="brand">
        <BrandMark />
        <div>
          <h1>Dachshund Gatekeeper</h1>
          <p>Local vision. Verifiable decisions.</p>
        </div>
      </div>
      <div className="source-switch" aria-label="Video source">
        <span className="source-label">Source</span>
        <div className="segments">
          <button className={sourceType === "camera" ? "active" : ""} onClick={onCamera}>IMX219 · CSI0</button>
          <button className={sourceType === "video" ? "active" : ""} onClick={onVideo}>Video file</button>
        </div>
      </div>
    </header>
  );
}
