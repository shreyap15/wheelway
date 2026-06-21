// Shared labels/notes that clearly separate the offline A* demo from real
// routing. Centralized so the wording is consistent across the mode switch and
// the demo view, and so it can be asserted in tests.

// The synthetic A* demo is OPT-IN: hidden from the presentation UI unless
// VITE_ENABLE_SYNTHETIC_DEMO is set. When off, the button is not rendered, the
// component is not mounted, and no simulated-data disclosures appear.
export function syntheticDemoEnabled(env = {}) {
  return Boolean(env.VITE_ENABLE_SYNTHETIC_DEMO);
}

export const REAL_MODE_LABEL = "Real Accessible Route";

export const SYNTHETIC_MODE_LABEL =
  "Accessibility Algorithm Demo — simulated path conditions";

export const SYNTHETIC_MODE_SUBLABEL =
  "Synthetic A* graph — not a real Berkeley network";

// Plain-language disclosure shown inside the demo view.
export const SYNTHETIC_MODE_NOTE = [
  "The A* algorithm and accessibility scoring logic are real.",
  "Stairs, slope, surface, width, and obstruction attributes in this mode are mocked to demonstrate route behavior.",
  "This is not a verified accessibility audit of Lower Sproul.",
  "Real-route mode uses Mapbox geometry and Google elevation data.",
];
