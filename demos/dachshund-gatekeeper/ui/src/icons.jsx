export function BrandMark() {
  return (
    <svg viewBox="0 0 128 58" aria-hidden="true" className="brand-mark">
      <path d="M7 40c9 0 14-6 14-14v-7c0-6 4-10 10-10h9l7-6 4 9c6 3 10 8 10 14H48c-6 0-9 3-9 8v6m-17-8H12l-6-5m15 13-5 11m22-11 4 11m-30 0h36" />
      <path d="M77 6v45m40-45v45M76 11h42M83 18h28v33H83zM89 23v22m8-22v22m8-22v22M72 51h50" />
    </svg>
  );
}

export function GateIcon({ locked = false }) {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="gate-icon">
      <path d="M15 22v-5a9 9 0 0 1 18 0v5" />
      <rect x="11" y="21" width="26" height="20" rx="3" />
      <path d={locked ? "M24 28v7" : "M24 28v7M33 16a9 9 0 0 0-17-3"} />
      <circle cx="24" cy="28" r="2" />
    </svg>
  );
}

export function PauseIcon({ paused }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {paused ? <path d="m8 5 11 7-11 7z" /> : <><path d="M7 5v14" /><path d="M17 5v14" /></>}
    </svg>
  );
}

export function CameraIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="4" /></svg>;
}

export function SourceIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="14" height="14" rx="2" /><path d="m17 10 4-3v10l-4-3z" /></svg>;
}

export function CloseIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}
