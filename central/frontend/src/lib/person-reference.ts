/* Previewing الرقم المرجعي while the operator types the identifiers it comes from.
 *
 * Only MILITARY derives, because only a service number is unique per force. Everyone else is
 * ISSUED a reference by the backend on save, so there is nothing to preview - and previewing a
 * guess would show a number that never becomes the person.
 *
 * `app/services/person_identity.py` is authoritative and re-derives on save. This exists only
 * so the read-only field is not blank while a military subject is being entered.
 */

import type { Subject } from "@/api/types";

function clean(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  return text || null;
}

/** Same conservative rule as the backend: fold case, whitespace and Arabic-Indic digits only. */
/** True when a person's stored name is really just their reference number.
 *
 * `person_identities.person_name` is NOT NULL, so `get_or_create_identity` falls back to the
 * reference when a subject is saved without a name - legitimate for someone who will not
 * identify themselves. The consequence is that "CIV-00000019" arrives as a person_name, and
 * rendering it puts a number where a human name belongs, twice over next to the reference.
 */
export function isPlaceholderName(
  name: string | null | undefined,
  reference: string | null | undefined,
): boolean {
  const n = normalizeReference(name);
  return n !== null && n === normalizeReference(reference);
}

export function normalizeReference(value: string | null | undefined): string | null {
  if (!value) return null;
  const folded = value
    .normalize("NFKC")
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[\u06f0-\u06f9]/g, (d) => String(d.charCodeAt(0) - 0x06f0));
  return folded.split(/\s+/).filter(Boolean).join(" ").toUpperCase() || null;
}

export function deriveReference(subject: Subject): string | null {
  // Military: the serial is unique within its force, so the force is part of the key.
  const militaryId = clean(subject.military_id);
  const branch = subject.security_branch;
  if (militaryId && branch && branch !== "OTHER") {
    return normalizeReference(`MIL-${branch}-${militaryId}`);
  }

  // Nothing else is previewed. A civilian reference is ISSUED by the backend (CIV-*), so the
  // form cannot know it before saving - showing a guess here would be showing a number that
  // never becomes the person.
  //
  // رقم السجل in particular used to be previewed as LBN-<CAZA>-<REGISTER>. It identifies a
  // family civil record, not one human, so relatives collapsed onto a single canonical
  // person. It stays on the form as searchable metadata and keys nothing.
  //
  // UNHCR / UNRWA numbers are trusted EXTERNAL identifiers now: they help find an existing
  // person, they are not that person’s reference.
  return null;
}
