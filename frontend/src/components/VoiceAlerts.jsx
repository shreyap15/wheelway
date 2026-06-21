import { useCallback, useEffect, useRef, useState } from "react";
import {
  ClientDedupe,
  classifyPlayError,
  fetchSpeech,
  insertByPriority,
  voiceBus,
} from "../services/speechClient";
import "./VoiceAlerts.css";

// Isolated voice-alert UI: on/off toggle, test button, priority audio queue,
// loading/error + autoplay-permission handling. Other code requests speech via
// `voiceBus.emit(alert)` (or imports deriveVoiceAlerts). The Deepgram key stays
// server-side; this only calls POST /speak.
export default function VoiceAlerts() {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | speaking | error | blocked
  const [error, setError] = useState("");
  const [queueLen, setQueueLen] = useState(0);

  const queueRef = useRef([]);
  const playingRef = useRef(false);
  const dedupeRef = useRef(new ClientDedupe(30000));
  const audioRef = useRef(null);
  const enabledRef = useRef(false);

  useEffect(() => {
    enabledRef.current = enabled;
    if (enabled) pump();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  const enqueue = useCallback((alert) => {
    if (!alert || !alert.text) return;
    // Suppress repeats of the same dedupe key within its TTL.
    if (!dedupeRef.current.claim(alert.dedupe_key)) return;
    queueRef.current = insertByPriority(queueRef.current, alert);
    setQueueLen(queueRef.current.length);
    pump();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Subscribe to the global voice bus once.
  useEffect(() => voiceBus.subscribe(enqueue), [enqueue]);

  async function pump() {
    if (playingRef.current || !enabledRef.current) return;
    const next = queueRef.current[0];
    if (!next) return;

    playingRef.current = true;
    setStatus("speaking");
    setError("");
    try {
      const result = await fetchSpeech(next);
      // Drop from queue regardless (suppressed or played) to avoid loops.
      queueRef.current = queueRef.current.slice(1);
      setQueueLen(queueRef.current.length);

      if (result.suppressed) {
        playingRef.current = false;
        setStatus("idle");
        return pump();
      }

      const url = URL.createObjectURL(result.blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        playingRef.current = false;
        setStatus("idle");
        pump();
      };
      try {
        await audio.play();
      } catch (err) {
        URL.revokeObjectURL(url);
        playingRef.current = false;
        if (classifyPlayError(err) === "autoplay-blocked") {
          // Re-queue this alert and wait for a user gesture.
          queueRef.current = [next, ...queueRef.current];
          setQueueLen(queueRef.current.length);
          setStatus("blocked");
          setError("Tap “Enable sound” to allow voice alerts.");
          return;
        }
        setStatus("error");
        setError("Playback failed.");
      }
    } catch (err) {
      queueRef.current = queueRef.current.slice(1);
      setQueueLen(queueRef.current.length);
      playingRef.current = false;
      setStatus("error");
      setError(
        err && err.status === 503
          ? "Voice synthesis is not configured on the server."
          : "Voice synthesis failed."
      );
    }
  }

  function toggle() {
    setEnabled((v) => !v);
  }

  function enableSound() {
    // User gesture clears the autoplay block and resumes the queue.
    setEnabled(true);
    setStatus("idle");
    setError("");
    playingRef.current = false;
    pump();
  }

  function testVoice() {
    if (!enabled) setEnabled(true);
    enqueue({
      type: "test",
      priority: "info",
      text: "Voice alerts are working.",
      dedupe_key: `test:${Math.floor(Date.now() / 1000)}`,
    });
  }

  return (
    <section className="voice-alerts">
      <div className="voice-row">
        <label className="voice-toggle">
          <input type="checkbox" checked={enabled} onChange={toggle} />
          Voice alerts
        </label>
        <button type="button" className="voice-test" onClick={testVoice}>
          Test voice
        </button>
        {queueLen > 0 && <span className="voice-queue">{queueLen} queued</span>}
        {status === "speaking" && <span className="voice-status">Speaking…</span>}
      </div>
      {status === "blocked" && (
        <div className="voice-banner">
          {error}{" "}
          <button type="button" onClick={enableSound}>
            Enable sound
          </button>
        </div>
      )}
      {status === "error" && <div className="voice-banner voice-error">{error}</div>}
    </section>
  );
}
