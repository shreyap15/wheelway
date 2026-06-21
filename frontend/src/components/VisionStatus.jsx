import { useEffect, useRef, useState } from "react";
import { voiceBus } from "../services/speechClient";
import {
  deriveBanner,
  freshnessSeconds,
  isCameraOnline,
  latestVisionObservation,
  ttcDisplay,
  visionStreamUrl,
  voiceKey,
} from "../visionStatus";
import "./VisionStatus.css";

// Debounce: keep a hazard banner visible briefly after CLEAR so it doesn't
// flicker, and so STOP text stays readable.
const CLEAR_DEBOUNCE_MS = 2500;

// Compact live "physical AI" status + hazard experience (presentation-safe).
// Consumes vision_modal observations the dashboard already polls; shows no raw
// physics/track-id/Redis fields.
export default function VisionStatus({ observations = [] }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [banner, setBanner] = useState(null);
  const [showStream, setShowStream] = useState(false);
  const [streamOk, setStreamOk] = useState(true);
  const lastVoiceKeyRef = useRef(null);
  const clearTimerRef = useRef(null);

  const streamUrl = visionStreamUrl(import.meta.env);

  // Tick for freshness/offline calculation.
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const latest = latestVisionObservation(observations);
  const cameraOnline = isCameraOnline(latest, nowMs);

  // Derive hazard banner + emit voice once per new actionable hazard.
  useEffect(() => {
    const next = deriveBanner(latest);
    if (next) {
      if (clearTimerRef.current) {
        clearTimeout(clearTimerRef.current);
        clearTimerRef.current = null;
      }
      setBanner(next);
      const key = voiceKey(latest);
      if (key && key !== lastVoiceKeyRef.current) {
        lastVoiceKeyRef.current = key;
        voiceBus.emit({
          type: `vision_${next.action.toLowerCase()}`,
          priority: next.level === "critical" ? "critical" : "warning",
          text: next.text,
          dedupe_key: key,
        });
      }
    } else if (!clearTimerRef.current) {
      // CLEAR/heartbeat: debounce the banner away (do not speak "clear").
      clearTimerRef.current = setTimeout(() => {
        setBanner(null);
        lastVoiceKeyRef.current = null;
        clearTimerRef.current = null;
      }, CLEAR_DEBOUNCE_MS);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latest]);

  const ttcText = banner ? ttcDisplay(latest) : null;
  const fresh = freshnessSeconds(latest, nowMs);

  return (
    <section className="vision-status">
      <div className="vision-head">
        <span className={`vision-dot ${cameraOnline ? "on" : "off"}`} />
        <strong>{cameraOnline ? "Obstacle detection active" : "Camera obstacle detection offline"}</strong>
        {cameraOnline && fresh != null && (
          <span className="vision-fresh">updated {fresh}s ago</span>
        )}
        {streamUrl && (
          <button type="button" className="vision-stream-toggle" onClick={() => setShowStream((v) => !v)}>
            {showStream ? "Hide camera" : "Show camera"}
          </button>
        )}
      </div>

      {banner ? (
        <div className={`vision-banner vision-${banner.level}`}>
          {banner.arrow && <span className="vision-arrow">{banner.arrow}</span>}
          <span className="vision-text">{banner.text}</span>
          {ttcText && <span className="vision-ttc">{ttcText}</span>}
        </div>
      ) : (
        cameraOnline && <p className="vision-clear">Path clear ahead.</p>
      )}

      {!cameraOnline && (
        <p className="vision-offline-note">Camera obstacle detection is unavailable.</p>
      )}

      {streamUrl && showStream && streamOk && (
        <div className="vision-stream">
          {/* Loaded directly from the Pi; hidden on error. Never blocks the map. */}
          <img
            src={`${streamUrl.replace(/\/$/, "")}/stream.mjpg`}
            alt="Annotated obstacle-detection stream"
            onError={() => setStreamOk(false)}
          />
        </div>
      )}
    </section>
  );
}
