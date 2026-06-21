import { useEffect, useState } from "react";
import {
  diagnosticsVisible,
  fetchHealth,
  subscribeDiag,
} from "../services/diagnostics";
import "./SponsorDiagnostics.css";

// Compact dev/demo-only panel. Hidden unless Vite DEV or VITE_SHOW_DIAGNOSTICS.
// Shows safe booleans/statuses + active session info. Never shows secrets/URLs.
export default function SponsorDiagnostics() {
  const [health, setHealth] = useState(null);
  const [err, setErr] = useState(false);
  const [session, setSession] = useState({});

  const visible = diagnosticsVisible(import.meta.env);

  useEffect(() => subscribeDiag(setSession), []);

  useEffect(() => {
    if (!visible) return undefined;
    let alive = true;
    const load = () =>
      fetchHealth()
        .then((h) => alive && setHealth(h))
        .catch(() => alive && setErr(true));
    load();
    const id = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [visible]);

  if (!visible) return null;

  const row = (label, value) => (
    <div className="diag-row">
      <span>{label}</span>
      <strong>{String(value)}</strong>
    </div>
  );

  return (
    <section className="sponsor-diagnostics">
      <p className="diag-title">Diagnostics (dev)</p>
      {err && <p className="diag-err">/health unavailable</p>}
      {health && (
        <>
          {row("storage mode", health.storage_mode)}
          {row("redis configured", health.redis_configured)}
          {row("redis connected", health.redis_connected)}
          {row("deepgram configured", health.deepgram_configured)}
          {row("mapbox configured", health.mapbox_configured)}
          {row("google enrichment", health.google_enrichment_configured)}
          {row("fetch.ai gateway", health.fetchai_gateway_configured)}
        </>
      )}
      {row("route session", session?.routeSessionId || "—")}
      {row("selected route", session?.selectedRouteId || "—")}
      {row("recent events", session?.eventCount ?? "—")}
      {row("latest alert", session?.latestAlert || "—")}
      {row("last speech", session?.speechStatus || "—")}
    </section>
  );
}
