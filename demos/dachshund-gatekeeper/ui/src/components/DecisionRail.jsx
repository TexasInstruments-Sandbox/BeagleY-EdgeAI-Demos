import { GateIcon, SourceIcon } from "../icons";

const friendlyState = {
  WATCHING: "WATCHING",
  TRACKING: "TRACKING",
  VERIFYING: "VERIFYING",
  AUTHORIZED: "AUTHORIZED",
  HELD: "HELD",
};

export function DecisionRail({ status, onChangeSource }) {
  const state = status.decision.state;
  const confidence = status.breed.score;
  return (
    <aside className={`decision-rail state-${state.toLowerCase()}`}>
      <section className="gate-decision">
        <h2>Gate decision</h2>
        <div className="decision-value"><GateIcon locked={state !== "AUTHORIZED"} /><strong>{friendlyState[state] || state}</strong></div>
      </section>
      <section className="current-subject">
        <h2>Current subject</h2>
        <div className="subject-name">{status.breed.label}</div>
        <span>Breed confidence</span>
        <strong className="confidence">{confidence == null ? "—" : `${(confidence * 100).toFixed(1)}%`}</strong>
      </section>
      <section className="tracker">
        <h2>Tracker state</h2>
        <div><i className="reticle" /><strong>{status.tracker.state}</strong><span>· {status.tracker.frames} frames</span></div>
      </section>
      <button className="change-source" onClick={onChangeSource}><SourceIcon /><span>Switch source</span></button>
    </aside>
  );
}
