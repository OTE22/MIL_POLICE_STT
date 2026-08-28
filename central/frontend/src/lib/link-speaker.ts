/* Binding a speaker to a canonical person.
 *
 * One place, because there is exactly one correct way to do it and it is easy to get subtly
 * wrong. Both the picker and تحديد الهوية call these; neither reimplements them.
 *
 * Two rules the whole file exists to protect, both of which were real bugs:
 *
 *   `person_name` is the CANONICAL name only - never a display label. The backend does no
 *   rank-stripping, so sending "الرائد علي حسن" files that rank as part of a person's name.
 *
 *   A reference the backend ISSUED is recovered by participant_key set-difference, never by
 *   matching a name. Two people in one session may share a name, and picking the wrong one
 *   attaches a speaker - and later their voice print - to the wrong human.
 *
 * `speaker_role` is deliberately absent from every PATCH here. Identifying a person and setting
 * الصفة are separate acts on the card, and quietly changing the role while linking would make
 * that promise false.
 */

import { http } from "@/api/client";
import type { Investigation, Speaker, Subject } from "@/api/types";
import { emptySubject } from "@/components/subjects/SubjectFields";
import { normalizeReference } from "@/lib/person-reference";

/** Someone already recorded on this session: their reference is known, so one PATCH is enough. */
export async function linkToSessionParticipant(
  sessionId: string,
  speakerId: string,
  person: { canonicalName: string; rank?: string | null; reference: string; displayName: string },
): Promise<Speaker> {
  return http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speakerId}`, {
    display_name: person.displayName,
    // The bare name. `displayName` may carry the rank; this may not.
    person_name: person.canonicalName,
    reference_number: person.reference,
  });
}

/** Someone from the registry, or newly entered: record them on the session, then link.
 *
 * Retry-safe by construction. The PUT is skipped when a subject with that reference is already
 * present, so a PATCH that fails AFTER the participant was created does not append a duplicate
 * when the operator tries again - the retry finds them and re-runs only the PATCH.
 */
export async function linkToRegistryPerson(
  sessionId: string,
  speakerId: string,
  person: { canonicalName: string; reference: string; displayName?: string; subject?: Subject },
): Promise<Speaker> {
  const current = await http.get<Investigation>(`/investigations/${sessionId}`);
  const subjects = current.subjects ?? [];

  let reference = person.reference;
  const normalized = normalizeReference(reference);
  const already = normalized !== null && subjects.some(
    (s) => normalizeReference(s.reference_number) === normalized,
  );

  if (!already) {
    const added: Subject = person.subject
      ? { ...person.subject, subject_name: person.canonicalName, reference_number: reference || null }
      : { ...emptySubject(), subject_name: person.canonicalName, reference_number: reference };
    const saved = await http.put<Investigation>(
      `/investigations/${sessionId}`, { subjects: [...subjects, added] },
    );
    if (!reference) {
      // The backend issued it. Find the participant that was not there before - never the one
      // whose name matches, because two people in one session may share one.
      const before = new Set(subjects.map((s) => s.participant_key));
      reference = (saved.subjects ?? []).find((s) => !before.has(s.participant_key))
        ?.reference_number ?? "";
    }
  }

  return linkToSessionParticipant(sessionId, speakerId, {
    canonicalName: person.canonicalName,
    reference,
    displayName: person.displayName ?? person.canonicalName,
  });
}

/** A working label for a voice nobody has placed yet.
 *
 * `display_name` and nothing else: no person_name, no reference, so no identity. The speaker
 * stays out of بصمات الأصوات and keeps offering تحديد الهوية, which is the honest outcome for
 * "I recognise this voice but cannot yet say whose it is".
 */
export async function setTemporaryLabel(
  sessionId: string,
  speakerId: string,
  label: string,
): Promise<Speaker> {
  return http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speakerId}`, {
    display_name: label.trim() || null,
  });
}
