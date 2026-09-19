/** Speaker identity is selected by UUID, never inferred from a name. */
import { http } from "@/api/client";
import type { Investigation, Speaker, Subject } from "@/api/types";
import { emptySubject } from "@/components/subjects/SubjectFields";

export async function linkToSessionParticipant(
  sessionId: string, speakerId: string,
  person: { canonicalName: string; identityId: string; displayName: string },
): Promise<Speaker> {
  return http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speakerId}`, {
    display_name: person.displayName,
    identity_id: person.identityId,
  });
}

export async function linkToRegistryPerson(
  sessionId: string, speakerId: string,
  person: { canonicalName: string; identityId?: string | null; displayName?: string; subject?: Subject },
): Promise<Speaker> {
  const current = await http.get<Investigation>(`/investigations/${sessionId}`);
  const subjects = current.subjects ?? [];
  let identityId = person.identityId || person.subject?.identity_id;
  if (!identityId || !subjects.some(s => s.identity_id === identityId)) {
    const added = { ...(person.subject ?? emptySubject()), subject_name: person.canonicalName,
                    identity_id: identityId ?? null };
    const saved = await http.put<Investigation>(`/investigations/${sessionId}`, { subjects: [...subjects, added] });
    const before = new Set(subjects.map(s => s.participant_key));
    identityId = saved.subjects.find(s => !before.has(s.participant_key))?.identity_id;
    // Keep the returned identity on the draft so retrying a failed speaker PATCH reuses it.
    if (person.subject && identityId) person.subject.identity_id = identityId;
  }
  if (!identityId) throw new Error("person_identity_required");
  return linkToSessionParticipant(sessionId, speakerId, {
    canonicalName: person.canonicalName, identityId,
    displayName: person.displayName ?? person.canonicalName,
  });
}

export async function setTemporaryLabel(sessionId: string, speakerId: string, label: string): Promise<Speaker> {
  return http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speakerId}`, { display_name: label.trim() || null });
}
