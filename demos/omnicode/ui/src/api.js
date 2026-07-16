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

export async function uploadMedia(file, onProgress) {
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
      } catch (error) { reject(error); }
    });
    request.addEventListener("error", () => reject(new Error("Upload failed")));
  });
  request.open("POST", `/api/upload?filename=${encodeURIComponent(file.name)}`);
  request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
  request.send(file);
  return result;
}

export const PREVIEW_STATUS = {
  paused: false,
  error: "",
  source: { type: "camera", label: "IMX219 · CSI0", isp_active: true },
  detections: [
    { left: .11, top: .19, width: .2, height: .34, score: .982, decoded: true },
    { left: .61, top: .17, width: .25, height: .23, score: .947, decoded: true },
    { left: .23, top: .66, width: .45, height: .17, score: .961, decoded: true },
  ],
  selected: {
    id: "d5d7588f21aa", timestamp: "2026-07-15T23:42:18Z", format: "QRCode",
    text: "https://beagleboard.org/beagley-ai", content_type: "Text",
    symbology_identifier: "]Q1", orientation: 0, detector_score: .982, decode_ms: 1.8, count: 6,
  },
  scans: [
    { id: "d5d7588f21aa", timestamp: "2026-07-15T23:42:18Z", format: "QRCode", text: "https://beagleboard.org/beagley-ai", detector_score: .982, count: 6 },
    { id: "0aee6376ad02", timestamp: "2026-07-15T23:42:16Z", format: "DataMatrix", text: "J722S-VPAC-TIDL", detector_score: .947, count: 4 },
    { id: "e54b28aa4c7d", timestamp: "2026-07-15T23:42:14Z", format: "Code128", text: "BEAGLEY-EDGEAI-2026", detector_score: .961, count: 3 },
    { id: "37190b66a470", timestamp: "2026-07-15T23:42:12Z", format: "EAN13", text: "9780201379624", detector_score: .934, count: 2 },
  ],
  performance: { fps: 27.1, end_to_end_ms: 36.4, detector_ms: 8.1, decoder_ms: 1.8 },
  acceleration: {
    active: true, label: "TIDL · C7x/MMA", cpu_fallback: 0,
    detector: { provider: "TIDLExecutionProvider", core: 1, nodes: 283, invocations: 18442 },
    decoder: { runtime: "ZXing-C++", version: "2.2.1", processor: "A53 CPU, TIDL-localized crops only", invocations: 9612 },
    remoteprocs: [{ firmware: "j722s-c71_0-fw", state: "running" }],
  },
  memory: { total_bytes: 4 * 1024 ** 3, available_bytes: 2.7 * 1024 ** 3, used_bytes: 1.3 * 1024 ** 3, process_rss_bytes: 302 * 1024 ** 2 },
  system: { cpu_percent: 31.2 },
  formats: "All ZXing 2.2 formats",
};
