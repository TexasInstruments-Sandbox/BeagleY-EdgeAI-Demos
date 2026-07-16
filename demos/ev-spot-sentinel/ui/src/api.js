export async function fetchStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) throw new Error(`Status request failed (${response.status})`);
  return response.json();
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok || value.ok === false) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}

export const changeSource = (type, path = "") => post("/api/source", { type, path });
export const control = (action) => post("/api/control", { action });
export const saveSpots = (spots) => post("/api/spots", { spots });

export function uploadVideo(file, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/api/upload?filename=${encodeURIComponent(file.name)}`);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.onload = () => {
      let value = {};
      try { value = JSON.parse(request.responseText); } catch { /* handled below */ }
      if (request.status >= 200 && request.status < 300) resolve(value);
      else reject(new Error(value.error || `Upload failed (${request.status})`));
    };
    request.onerror = () => reject(new Error("Video upload lost its connection"));
    request.send(file);
  });
}

export const PREVIEW_STATUS = {
  captured_utc: "2026-07-15T21:32:00Z", paused: false, error: "",
  source: { type: "video", label: "ev-spot-demo.mp4", isp_active: false },
  spots: [
    { id: "EV-A", name: "EV · A", polygon: [[.02,.46],[.32,.46],[.34,.98],[0,.98]], occupied: false, state: "AVAILABLE", dwell_seconds: 0, vehicle: null, plate: null },
    { id: "EV-B", name: "EV · B", polygon: [[.34,.46],[.66,.46],[.68,.98],[.32,.98]], occupied: true, state: "OVERSTAY", dwell_seconds: 2142, overstay: true, vehicle: { label: "car", score: .91, box: { left: .10, top: .16, width: .79, height: .71 } }, plate: { text: "5AU5341", score: .91, region: "Czech Republic", box: { left: .59, top: .58, width: .16, height: .08 } } },
    { id: "EV-C", name: "EV · C", polygon: [[.68,.46],[.98,.46],[1,.98],[.66,.98]], occupied: false, state: "AVAILABLE", dwell_seconds: 0, vehicle: null, plate: null },
  ],
  recent_sessions: [
    { id: 12, spot_id: "EV-B", started_utc: "2026-07-15T20:56:18Z", ended_utc: null, duration_seconds: 2142, plate: "5AU5341", plate_confidence: .91, vehicle_type: "car", overstay: 1 },
    { id: 11, spot_id: "EV-A", started_utc: "2026-07-15T19:03:00Z", ended_utc: "2026-07-15T20:07:15Z", duration_seconds: 3855, plate: "LXR7421", plate_confidence: .86, vehicle_type: "car", overstay: 1 },
  ],
  leaderboard: [
    { plate: "LXR7421", visits: 3, total_seconds: 8775, longest_seconds: 3855, last_seen_utc: "2026-07-15T20:07:15Z" },
    { plate: "5AU5341", visits: 1, total_seconds: 2142, longest_seconds: 2142, last_seen_utc: "2026-07-15T21:32:00Z", active: true },
  ],
  policy: { overstay_seconds: 1800, retention_days: 30, local_only: true, human_review_required: true },
  performance: { fps: 7.4, frames: 3821, end_to_end_ms: 134.6, vehicle_inference_ms: 93.2, plate_inference_ms: 417.4 },
  acceleration: { active: true, label: "C7x/MMA ACTIVE", cpu_fallback: 0, vehicle: { provider: "TIDLExecutionProvider", core: 1, nodes: 283, invocations: 3821, cpu_fallback: false }, plate: { provider: "CPUExecutionProvider", invocations: 42 }, isp: { active: false, pipeline: "IMX219 CSI0 → VPAC VISS → NV12" } },
  memory: { total_bytes: 4000000000, used_bytes: 1880000000, available_bytes: 2120000000, process_rss_bytes: 416000000 },
  system: { cpu_percent: 36.2 },
};
