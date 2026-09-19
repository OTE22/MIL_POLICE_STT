from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def edit(path, fn):
    p = ROOT / path
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')
import re

base = 'central/frontend/src/'
def types(s):
    s = re.sub(r'^  (?:reference_number|identity_reference|person_reference|enrolled_person_reference|reference):.*\n', '', s, flags=re.M)
    for name in ['Subject', 'Profile', 'InvestigatorBrief']:
        s = s.replace(f'export interface {name} {{', f'export interface {name} {{\n  identity_id?: string | null;')
    return s
edit(base+'api/types.ts', types)
def subject(s):
    s = s.replace('useEffect, ', '').replace('import { useAuth } from "@/lib/auth";\n', '').replace('import { deriveReference, normalizeReference } from "@/lib/person-reference";\n', '')
    s = s.replace('    reference_number: "",', '    identity_id: null,')
    start = s.index('  const derived =')
    end = s.index('  const setPersonType', start)
    s = s[:start] + s[end:]
    start = s.index('        {/* الرقم المرجعي')
    end = s.index('        {/* ---- military', start)
    return s[:start] + s[end:]
edit(base+'components/subjects/SubjectFields.tsx', subject)
edit(base+'pages/InvestigationFormPage.tsx', lambda s: s.replace('reference_number: clean(s.reference_number)', 'identity_id: s.identity_id ?? null'))
edit(base+'pages/InvestigationDetailPage.tsx', lambda s: re.sub(r'^.*s.reference_number.*\n', '', s, flags=re.M))
edit(base+'pages/ReportComposerPage.tsx', lambda s: re.sub(r'^.*sp.reference.*\n', '', s, flags=re.M))
edit(base+'components/transcript/SpeakersPanel.tsx', lambda s: re.sub(r'        <Field label=\{T.referenceNumber\}>.*?</Field>\s*', '', s, flags=re.S))

(ROOT/base/'lib/link-speaker.ts').write_text('''/** Speaker identity is selected by UUID, never inferred from a name. */
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
''', encoding='utf-8')

def identify(s):
    s = s.replace('useEffect, useMemo, useState', 'useEffect, useState').replace('import { normalizeReference } from "@/lib/person-reference";\n', '')
    start = s.index('/** The canonical identity key')
    end = s.index('export function IdentifySpeakerDialog', start)
    s = s[:start] + s[end:]
    start = s.index('  // Typing a reference')
    end = s.index('  const submit =', start)
    s = s[:start] + '''  const canSubmit = mode === "existing" ? picked !== null : Boolean(subject.subject_name?.trim());

''' + s[end:]
    s = s.replace('    const reference = mode === "existing" ? picked!.person_reference : referenceOf(subject);', '    const identityId = mode === "existing" ? picked!.identity_id : subject.identity_id;')
    s = s.replace('        reference,', '        identityId,')
    s = s.replace('data-reference={r.person_reference}', 'data-identity-id={r.identity_id}')
    s = re.sub(r'^.*<span className="ltr muted">\{r.person_reference\}</span>.*\n', '', s, flags=re.M)
    start = s.index('          {existingMatch && (')
    end = s.index('          {/* The same form', start)
    s = s[:start] + s[end:]
    return s
edit(base+'components/voice/IdentifySpeakerDialog.tsx', identify)

def picker(s):
    s = s.replace('import { isPlaceholderName, normalizeReference } from "@/lib/person-reference";\n', '')
    s = s.replace('data-reference={person.reference_number ?? ""}', 'data-identity-id={person.identity_id ?? ""}')
    s = re.sub(r'      <span className="ltr muted">\s*\{person.reference_number \?\? T.pickPersonIncomplete\}\s*</span>', '      {!person.selectable && <span className="muted">{T.pickPersonIncomplete}</span>}', s)
    s = s.replace('normalizeReference(p.reference_number)', 'p.identity_id').replace('normalizeReference(r.person_reference)', 'r.identity_id')
    s = s.replace('reference: person.reference_number!', 'identityId: person.identity_id!').replace('p.reference_number', 'p.identity_id').replace('inv.reference_number', 'inv.identity_id')
    s = s.replace('data-reference={r.person_reference}', 'data-identity-id={r.identity_id}').replace('reference: r.person_reference', 'identityId: r.identity_id')
    s = re.sub(r'\{isPlaceholderName\(r.person_name, r.person_reference\).*?: r.person_name\}', '{r.person_name || T.unnamed}', s, flags=re.S)
    s = s.replace('                      <span className="ltr muted">{r.person_reference}</span>\n', '')
    return s
edit(base+'components/transcript/SpeakerPicker.tsx', picker)

def enroll(s):
    s = s.replace('  reference: string;', '  identityId: string;').replace('  const [reference, setReference] = useState(target.reference);\n', '').replace('    setReference(target.reference);\n', '')
    s = s.replace('!reference.trim()', '!target.identityId')
    s = re.sub(r'      <Field label=\{T.voicePersonReference\}.*?</Field>\n', '', s, flags=re.S)
    return s
edit(base+'components/voice/EnrollDialog.tsx', enroll)
edit(base+'components/transcript/VoiceSuggestion.tsx', lambda s: s.replace('reference: speaker.identity_reference ?? ""', 'identityId: speaker.identity_id ?? ""'))

def enrollments(s):
    s = s.replace('  reference: string;\n', '').replace('      reference: row.person_reference,\n', '').replace('  const [reference, setReference] = useState(person.reference);\n', '').replace('        person_reference: reference.trim(),\n', '').replace(' || !reference.trim()', '')
    s = re.sub(r'      <Field label=\{T.voicePersonReference\}.*?</Field>\n', '', s, flags=re.S)
    s = s.replace('data-reference={person.reference}', 'data-identity-id={person.identityId}').replace('data-reference={c.person_reference}', 'data-identity-id={c.identity_id}')
    s = re.sub(r'^.*<span.*\{(?:person.reference|c.person_reference)\}</span>.*\n', '', s, flags=re.M)
    s = s.replace('`${g.reference} (${g.prints.length})`', '`${g.name} (${g.prints.length})`').replace('reference: c.person_reference', 'identityId: c.identity_id')
    return s
edit(base+'pages/VoiceEnrollmentsPage.tsx', enrollments)

edit('central/backend/app/models/voice.py', lambda s: s.replace('Index("ix_voice_enrollment_person_model", "person_reference", "model")', 'Index("ix_voice_enrollment_identity_model", "identity_id", "model")'))
