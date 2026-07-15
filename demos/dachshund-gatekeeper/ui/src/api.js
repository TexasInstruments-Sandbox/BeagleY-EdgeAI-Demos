export async function fetchStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
  return response.json();
}

async function postJson(path, value) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}

export const changeSource = (type, path = "") => postJson("/api/source", { type, path });
export const control = (action) => postJson("/api/control", { action });

export async function uploadVideo(file, onProgress) {
  const request = new XMLHttpRequest();
  const result = new Promise((resolve, reject) => {
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    });
    request.addEventListener("load", () => {
      try {
        const body = JSON.parse(request.responseText);
        if (request.status >= 200 && request.status < 300 && body.ok) resolve(body);
        else reject(new Error(body.error || `Upload failed: ${request.status}`));
      } catch (error) {
        reject(error);
      }
    });
    request.addEventListener("error", () => reject(new Error("Upload failed")));
  });
  request.open("POST", `/api/upload?filename=${encodeURIComponent(file.name)}`);
  request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
  request.send(file);
  return result;
}

export const PREVIEW_STATUS = {
  uptime_seconds: 8263,
  paused: false,
  error: "",
  source: { type: "camera", label: "IMX219 · CSI0", isp_active: true },
  decision: { state: "AUTHORIZED", target_breed: "Dachshund", threshold: 0.72, stable_frames_required: 3 },
  detection: {
    present: true,
    score: 0.962,
    inference_ms: 18.4,
    box_normalized: { left: 0.365, top: 0.25, width: 0.26, height: 0.62 },
  },
  breed: { label: "Dachshund", score: 0.987, inference_ms: 6.9, tidl_run_ms: 6.61, top5: [] },
  tracker: { state: "LOCKED", frames: 18 },
  performance: { fps: 24.8, end_to_end_ms: 31, frames: 18442 },
  acceleration: {
    active: true,
    label: "C7x/MMA ACTIVE",
    cpu_fallback: 0,
    detector: { runtime: "ONNX Runtime", provider: "TIDLExecutionProvider", core: 1, nodes: 283, invocations: 18442 },
    breed: { runtime: "TFLite", delegate: "libtidl_tfl_delegate.so", core: 2, operators: 71, delegate_groups: 1, invocations: 5631 },
    remoteprocs: [
      { firmware: "j722s-c71_0-fw", state: "running" },
      { firmware: "j722s-c71_1-fw", state: "running" },
    ],
  },
  memory: {
    total_bytes: 2.5 * 1024 ** 3,
    available_bytes: 1.87 * 1024 ** 3,
    used_bytes: 642 * 1024 ** 2,
    process_rss_bytes: 291 * 1024 ** 2,
  },
  system: { cpu_percent: 38.2 },
  events: [
    { timestamp: "2026-07-15T15:24:31.512Z", state: "AUTHORIZED", title: "Dachshund admitted", confidence: 0.987 },
    { timestamp: "2026-07-15T15:24:12.103Z", state: "HELD", title: "Unknown breed held", confidence: 0.621 },
    { timestamp: "2026-07-15T15:23:58.774Z", state: "AUTHORIZED", title: "Dachshund admitted", confidence: 0.979 },
  ],
};
