import { useEffect, useRef, useState } from "react";
import {
  buildGeocodeUrl,
  isLatestResponse,
  parseGeocodeResults,
} from "./placeSearch";

// Autocomplete place input backed by Mapbox Geocoding. Debounced, abortable, and
// stale-response-guarded. Emits a selected {name, address, lat, lng} via onSelect.
export default function PlaceSearch({
  label,
  placeholder,
  selected,
  onSelect,
  token,
  proximity,
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  // idle | loading | no-results | error
  const [state, setState] = useState("idle");
  const [geoState, setGeoState] = useState(null); // null | locating | denied | unavailable

  const seqRef = useRef(0); // newest issued request sequence
  const appliedRef = useRef(0); // newest applied response sequence
  const abortRef = useRef(null);
  const timerRef = useRef(null);

  // Debounced search whenever the typed query changes.
  useEffect(() => {
    const q = query.trim();
    if (selected && q === selected.name) return; // don't re-search the chosen value
    if (q.length < 3) {
      setResults([]);
      setState("idle");
      setOpen(false);
      return;
    }
    if (!token) {
      setState("error");
      setOpen(true);
      return;
    }
    timerRef.current && clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      const seq = ++seqRef.current;
      setState("loading");
      setOpen(true);
      abortRef.current && abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const resp = await fetch(buildGeocodeUrl(q, token, { proximity }), {
          signal: controller.signal,
        });
        const data = await resp.json();
        // Drop stale responses (an older request resolving after a newer one).
        if (!isLatestResponse(seq, appliedRef.current)) return;
        appliedRef.current = seq;
        const parsed = parseGeocodeResults(data);
        setResults(parsed);
        setState(parsed.length ? "idle" : "no-results");
      } catch (err) {
        if (err.name === "AbortError") return;
        if (!isLatestResponse(seq, appliedRef.current)) return;
        appliedRef.current = seq;
        setState("error");
      }
    }, 300);
    return () => timerRef.current && clearTimeout(timerRef.current);
  }, [query, token, selected, proximity]);

  function choose(place) {
    onSelect(place);
    setQuery(place.name);
    setResults([]);
    setOpen(false);
    setState("idle");
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setGeoState("unavailable");
      return;
    }
    setGeoState("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeoState(null);
        choose({
          name: "Current location",
          address: "Current location",
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
      },
      (err) => {
        setGeoState(err && err.code === 1 ? "denied" : "unavailable");
      },
      { timeout: 10000 }
    );
  }

  return (
    <div className="place-search">
      <label className="place-search-label">
        {label}
        <div className="place-search-row">
          <input
            type="text"
            placeholder={placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length && setOpen(true)}
            aria-label={label}
          />
          <button
            type="button"
            className="place-loc-btn"
            onClick={useCurrentLocation}
            title="Use current location"
          >
            📍
          </button>
        </div>
      </label>

      {open && (
        <div className="place-results">
          {state === "loading" && <div className="place-msg">Searching…</div>}
          {state === "no-results" && <div className="place-msg">No matching places.</div>}
          {state === "error" && (
            <div className="place-msg">Place search unavailable.</div>
          )}
          {state === "idle" &&
            results.map((r) => (
              <button
                key={r.id}
                type="button"
                className="place-option"
                onClick={() => choose(r)}
              >
                <strong>{r.name}</strong>
                <span>{r.address}</span>
              </button>
            ))}
        </div>
      )}

      {geoState === "locating" && <p className="place-hint">Locating…</p>}
      {geoState === "denied" && (
        <p className="place-hint place-hint-error">Location permission denied.</p>
      )}
      {geoState === "unavailable" && (
        <p className="place-hint place-hint-error">Location unavailable.</p>
      )}
      {selected && (
        <p className="place-selected">
          ✓ {selected.name}
          {selected.address && selected.address !== selected.name
            ? ` — ${selected.address}`
            : ""}
        </p>
      )}
    </div>
  );
}
