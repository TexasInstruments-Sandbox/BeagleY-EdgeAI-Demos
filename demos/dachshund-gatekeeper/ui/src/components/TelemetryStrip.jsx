const formatBytes = (bytes) => {
  if (!bytes) return "0 MB";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
};

export function TelemetryStrip({ status }) {
  const memoryPercent = status.memory.total_bytes ? status.memory.used_bytes / status.memory.total_bytes * 100 : 0;
  const sourceStage = status.source.type === "camera" ? "CSI0" : "Decoder";
  const stages = [sourceStage, ...(status.source.isp_active ? ["ISP"] : []), "TIDL detector", "TIDL breed"];
  return (
    <section className="telemetry-strip" aria-label="Pipeline and accelerator telemetry">
      <div className="pipeline-block">
        <h2>Pipeline</h2>
        <div className="pipeline-trace">
          {stages.map((stage) => <span key={stage}><i />{stage}</span>)}
        </div>
      </div>
      <Metric label="Performance" value={`${status.performance.fps.toFixed(1)} FPS`} detail={`${status.performance.end_to_end_ms.toFixed(0)} ms end-to-end`} />
      <Metric label="Detector" value={status.detection.inference_ms == null ? "—" : `${status.detection.inference_ms.toFixed(1)} ms`} detail="ONNX · C7x-1" />
      <Metric label="Breed" value={status.breed.inference_ms == null ? "—" : `${status.breed.inference_ms.toFixed(1)} ms`} detail="TFLite · C7x-2" />
      <Metric label="Accelerator" value={status.acceleration.active ? status.acceleration.label : "WARMING UP"} detail="283 nodes + 71 ops" accent />
      <Metric label="CPU fallback" value={String(status.acceleration.cpu_fallback)} detail="strictly disabled" accent />
      <div className="memory-block">
        <h2>System</h2>
        <strong>RAM {formatBytes(status.memory.used_bytes)} / {formatBytes(status.memory.total_bytes)}</strong>
        <span>CPU {(status.system?.cpu_percent ?? 0).toFixed(1)}% · process {formatBytes(status.memory.process_rss_bytes)}</span>
        <div className="memory-track"><i style={{ width: `${Math.min(100, memoryPercent)}%` }} /></div>
      </div>
    </section>
  );
}

function Metric({ label, value, detail, accent = false }) {
  return <div className={`metric ${accent ? "accent" : ""}`}><h2>{label}</h2><strong>{value}</strong><span>{detail}</span></div>;
}
