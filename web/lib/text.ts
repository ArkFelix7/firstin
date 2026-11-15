// Display-time cleanup for backend strings. Some backend values join two facts
// with a spaced em dash, e.g. "Utility room <dash> Floor 1".
// We never render the dash: split into a primary value and a secondary detail.

const DASH_SPLIT = /\s+[\u2014\u2013]\s+|\s*\u2014\s*/;

export function splitDetail(s: string): { main: string; detail: string | null } {
  const parts = s.split(DASH_SPLIT).map((x) => x.trim()).filter(Boolean);
  if (parts.length <= 1) return { main: parts[0] ?? s, detail: null };
  return { main: parts[0], detail: parts.slice(1).join(", ") };
}

/** Replace any dash separators with a comma for running prose (voice brief, log lines). */
export function clean(s: string): string {
  return s.replace(/\s+[\u2014\u2013]\s+/g, ", ").replace(/\u2014/g, ", ");
}

/** "Rooftop solar array (energized PV) (Roof)" style or dash-joined hazard strings. */
export function splitHazard(h: string): { type: string; loc: string | null } {
  const d = splitDetail(h);
  if (d.detail) return { type: d.main, loc: d.detail };
  const m = h.match(/^(.*\S)\s+\(([^()]+)\)$/);
  if (m && /floor|roof|suite|side|level|basement|lobby|dock|wing|north|south|east|west/i.test(m[2])) return { type: m[1], loc: m[2] };
  return { type: h, loc: null };
}

export function sentence(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
