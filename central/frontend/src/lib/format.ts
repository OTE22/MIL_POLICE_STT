const pad = (n: number) => String(Math.floor(n)).padStart(2, "0");

/** 0-based seconds -> HH:MM:SS (always LTR digits). */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "00:00:00";
  const s = Math.max(0, seconds);
  return `${pad(s / 3600)}:${pad((s % 3600) / 60)}:${pad(s % 60)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h} س ${m} د`;
  if (m > 0) return `${m} د ${sec} ث`;
  return `${sec} ث`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = value.length <= 10 ? new Date(`${value}T00:00:00`) : new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

/** Plain YYYY/MM/DD HH:MM (no locale punctuation, so RTL bidi never reorders it). */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return value.slice(0, 5);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function nowTime(): string {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function speakerColor(label: string): string {
  const m = /SPEAKER_(\d+)/.exec(label);
  const idx = m ? Number(m[1]) : 9;
  return idx <= 3 ? `var(--speaker-${idx})` : "var(--speaker-x)";
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]).join("");
}

/** How a person is SHOWN: rank first, then the name.
 *
 *  A label, never a key. `person_identities.person_name` holds the name ALONE and
 *  `reference_number` is the only identity key - joining them here and re-splitting them
 *  anywhere else is exactly what filed "الرائد علي عباس" as a canonical person. Nothing
 *  produced by this module may be sent back as `person_name`.
 */
export function personLabel(name: string | null | undefined, rank?: string | null): string {
  return [rank?.trim(), name?.trim()].filter(Boolean).join(" ");
}

/** The same label with الرقم المرجعي appended, for PLAIN-TEXT slots that cannot hold an
 *  element: title=, aria-label=, <option> children.
 *
 *  The reference is wrapped in U+2068 FIRST STRONG ISOLATE ... U+2069 POP DIRECTIONAL
 *  ISOLATE - the text-level equivalent of `<span className="ltr">`. Without it Arabic bidi
 *  reorders "MIL-ARMY-4471" against the separator. In JSX prefer the existing markup, which
 *  styles as well as isolates.
 */
export function personLabelWithReference(
  name: string | null | undefined,
  rank?: string | null,
  reference?: string | null,
): string {
  const label = personLabel(name, rank);
  const ref = reference?.trim();
  if (!ref) return label;
  // Explicit codepoints: FSI/PDI are invisible in source and trivially deleted by
  // accident, and a bare middot lets bidi reorder the reference against it.
  const FSI = String.fromCharCode(0x2068);
  const PDI = String.fromCharCode(0x2069);
  const MIDDOT = String.fromCharCode(0x00b7);
  const isolated = `${FSI}${ref}${PDI}`;
  return label ? `${label} ${MIDDOT} ${isolated}` : isolated;
}
