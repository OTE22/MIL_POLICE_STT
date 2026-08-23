/* بيانات الشخص — subject identity section of the investigation form.

   Cascade: نوع الشخص → (عسكري: الجهاز/الرتبة/الرقم العسكري) | (مدني: الجنسية →
   لبناني: رقم السجل + محل القيد | غير لبناني: بلد الجنسية) | (غير محدد: السبب)
   Documents are a list: a person may present several, or none at all.
   Nothing here is mandatory — a session can be saved for an unidentified person. */

import { useRef, useState } from "react";

import { ApiError, api, getToken } from "@/api/client";
import type {
  IdentityConfidence,
  PersonType,
  SecurityBranch,
  Subject,
  SubjectDocument,
  SubjectDocumentType,
  UndocumentedReason,
} from "@/api/types";
import { OTHER_COUNTRIES, PRIORITY_COUNTRIES, countryName, isLebanese } from "@/lib/countries";
import { formatBytes, formatDate } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Badge, Field, useToast } from "@/components/ui";
import { IconFile, IconPlus, IconUpload, IconX } from "@/components/Icons";

const PERSON_TYPES: PersonType[] = ["CIVILIAN", "MILITARY", "UNKNOWN"];
const BRANCHES: SecurityBranch[] = ["ARMY", "ISF", "GENERAL_SECURITY", "STATE_SECURITY", "CUSTOMS", "OTHER"];
const CONFIDENCES: IdentityConfidence[] = ["DECLARED", "DOCUMENT_SEEN", "VERIFIED"];
const REASONS: UndocumentedReason[] = ["NO_DOCUMENTS", "REFUSED", "UNIDENTIFIED", "DOCUMENTS_WITHHELD", "OTHER"];

const LEBANESE_DOCS: SubjectDocumentType[] = ["NATIONAL_ID", "CIVIL_EXTRACT", "PASSPORT", "DRIVING_LICENSE", "OTHER"];
const FOREIGN_DOCS: SubjectDocumentType[] = [
  "PASSPORT",
  "RESIDENCY_PERMIT",
  "UNHCR_CARD",
  "UNRWA_CARD",
  "REFUGEE_TRAVEL_DOC",
  "DRIVING_LICENSE",
  "OTHER",
];
const MILITARY_DOCS: SubjectDocumentType[] = ["MILITARY_ID", "NATIONAL_ID", "CIVIL_EXTRACT", "PASSPORT", "OTHER"];

export function emptySubject(): Subject {
  return {
    subject_name: "",
    reference_number: "",
    person_type: "CIVILIAN",
    military_id: "",
    rank: "",
    unit: "",
    department: "",
    security_branch: null,
    nationality_code: "LB",
    nationality_name: "",
    register_number: "",
    place_of_registration: "",
    is_unregistered: false,
    is_undocumented: false,
    undocumented_reason: null,
    identity_confidence: "DECLARED",
    notes: "",
    documents: [],
  };
}

export function emptyDocument(type: SubjectDocumentType): SubjectDocument {
  return {
    document_type: type,
    document_number: "",
    issuing_country: "",
    issue_date: null,
    expiry_date: null,
    notes: "",
  };
}

function documentTypesFor(subject: Subject): SubjectDocumentType[] {
  if (subject.person_type === "MILITARY") return MILITARY_DOCS;
  if (subject.person_type === "UNKNOWN") return FOREIGN_DOCS;
  return isLebanese(subject.nationality_code) ? LEBANESE_DOCS : FOREIGN_DOCS;
}

/* ------------------------------------------------------------------ one document */

function DocumentRow({
  sessionId,
  doc,
  types,
  canUpload,
  onChange,
  onRemove,
}: {
  sessionId: string | undefined;
  doc: SubjectDocument;
  types: SubjectDocumentType[];
  canUpload: boolean;
  onChange: (d: SubjectDocument) => void;
  onRemove: () => void;
}) {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof SubjectDocument, v: string | null) => onChange({ ...doc, [k]: v });

  const upload = async (file: File) => {
    if (!sessionId || !doc.id) {
      toast.warning(T.documentSaveFirst);
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const updated = await api<SubjectDocument>(
        `/investigations/${sessionId}/subject-documents/${doc.id}/file`,
        { method: "POST", body: form },
      );
      onChange(updated);
      toast.success(T.documentUploaded);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const removeFile = async () => {
    if (!sessionId || !doc.id) return;
    setBusy(true);
    try {
      await api(`/investigations/${sessionId}/subject-documents/${doc.id}/file`, { method: "DELETE" });
      onChange({ ...doc, has_file: false, original_filename: null, mime_type: null, size_bytes: null, sha256: null });
      toast.success(T.documentFileDeleted);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  const openFile = () => {
    if (!sessionId || !doc.id) return;
    // Authenticated fetch → object URL, so the token is never put in a URL.
    void (async () => {
      try {
        const res = await fetch(`/api/investigations/${sessionId}/subject-documents/${doc.id}/file`, {
          headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        });
        if (!res.ok) throw new ApiError(res.status, "document_file_not_found");
        const url = URL.createObjectURL(await res.blob());
        window.open(url, "_blank", "noopener,noreferrer");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch (err) {
        toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
      }
    })();
  };

  return (
    <div className="doc-row" data-testid="document-row">
      <div className="form-grid form-grid-3">
        <Field label={T.documentType} required>
          <select
            className="select"
            value={doc.document_type}
            onChange={(e) => set("document_type", e.target.value)}
            data-testid="document-type"
          >
            {types.map((x) => (
              <option key={x} value={x}>
                {t(`doc_${x}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={T.documentNumber}>
          <input className="input" dir="ltr" value={doc.document_number ?? ""} onChange={(e) => set("document_number", e.target.value)} maxLength={100} />
        </Field>
        <Field label={T.issuingCountry}>
          <input className="input" value={doc.issuing_country ?? ""} onChange={(e) => set("issuing_country", e.target.value)} maxLength={100} />
        </Field>
        <Field label={T.issueDate}>
          <input className="input" type="date" value={doc.issue_date ?? ""} onChange={(e) => set("issue_date", e.target.value || null)} />
        </Field>
        <Field label={T.expiryDate}>
          <input className="input" type="date" value={doc.expiry_date ?? ""} onChange={(e) => set("expiry_date", e.target.value || null)} />
        </Field>
        <Field label={T.notes}>
          <input className="input" value={doc.notes ?? ""} onChange={(e) => set("notes", e.target.value)} maxLength={2000} />
        </Field>
      </div>

      <div className="flex between wrap doc-file">
        <div className="flex wrap">
          {doc.has_file ? (
            <>
              <span className="file-chip">
                <IconFile width={14} height={14} />
                <span className="ltr">{doc.original_filename}</span>
                <span className="muted">({formatBytes(doc.size_bytes ?? null)})</span>
              </span>
              <button className="btn btn-sm" type="button" onClick={openFile}>
                {T.viewDocumentFile}
              </button>
              {canUpload && (
                <button className="btn btn-sm btn-ghost" type="button" onClick={() => void removeFile()} disabled={busy}>
                  {T.deleteDocumentFile}
                </button>
              )}
            </>
          ) : (
            <>
              <span className="muted small">{T.noFileUploaded}</span>
              {canUpload && (
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => (doc.id ? fileInput.current?.click() : toast.warning(T.documentSaveFirst))}
                  disabled={busy || !doc.id}
                  title={doc.id ? T.uploadDocumentFile : T.documentSaveFirst}
                  data-testid="upload-document"
                >
                  <IconUpload width={14} height={14} /> {T.uploadDocumentFile}
                </button>
              )}
              <span className="hint">{canUpload && doc.id ? T.documentFileHint : T.documentSaveFirst}</span>
            </>
          )}
          {doc.is_expired && <Badge kind="amber">{T.documentExpired}</Badge>}
        </div>
        <button className="icon-btn" type="button" onClick={onRemove} title={T.removeDocument} aria-label={T.removeDocument}>
          <IconX />
        </button>
      </div>
      <input
        ref={fileInput}
        type="file"
        className="sr-only"
        accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf"
        onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ one subject */

export function SubjectFields({
  sessionId,
  subject,
  index,
  canRemove,
  canUploadDocuments,
  onChange,
  onRemove,
}: {
  sessionId?: string;
  subject: Subject;
  index: number;
  canRemove: boolean;
  canUploadDocuments: boolean;
  onChange: (s: Subject) => void;
  onRemove: () => void;
}) {
  const set = <K extends keyof Subject>(k: K, v: Subject[K]) => onChange({ ...subject, [k]: v });
  const types = documentTypesFor(subject);
  const lebanese = isLebanese(subject.nationality_code);

  const setPersonType = (value: PersonType) =>
    onChange({
      ...subject,
      person_type: value,
      // Unidentified persons carry no document data by definition.
      is_undocumented: value === "UNKNOWN" ? true : subject.is_undocumented,
      undocumented_reason: value === "UNKNOWN" ? subject.undocumented_reason ?? "UNIDENTIFIED" : subject.undocumented_reason,
      nationality_code: value === "CIVILIAN" ? subject.nationality_code ?? "LB" : subject.nationality_code,
    });

  return (
    <div className="subject-card" data-testid="subject-card" data-index={index}>
      {canRemove && (
        <button className="icon-btn subject-remove" type="button" onClick={onRemove} aria-label={T.removeSubject} title={T.removeSubject}>
          <IconX />
        </button>
      )}

      <div className="form-grid form-grid-3">
        {/* ---- classification ------------------------------------------- */}
        <Field label={T.personType} required full>
          <div className="radio-row" role="radiogroup" aria-label={T.personType}>
            {PERSON_TYPES.map((x) => (
              <label key={x} className={`radio-chip ${subject.person_type === x ? "selected" : ""}`}>
                <input
                  type="radio"
                  name={`person_type_${index}`}
                  checked={subject.person_type === x}
                  onChange={() => setPersonType(x)}
                  data-testid={`person-type-${x}`}
                />
                {t(`person_${x}`)}
              </label>
            ))}
          </div>
        </Field>

        <Field label={T.subjectName}>
          <input className="input" value={subject.subject_name ?? ""} onChange={(e) => set("subject_name", e.target.value)} maxLength={200} />
        </Field>
        <Field label={T.referenceNumber}>
          <input className="input" value={subject.reference_number ?? ""} onChange={(e) => set("reference_number", e.target.value)} maxLength={100} />
        </Field>

        {/* ---- military -------------------------------------------------- */}
        {subject.person_type === "MILITARY" && (
          <>
            <Field label={T.securityBranch}>
              <select className="select" value={subject.security_branch ?? ""} onChange={(e) => set("security_branch", (e.target.value || null) as SecurityBranch | null)}>
                <option value="">{T.none}</option>
                {BRANCHES.map((b) => (
                  <option key={b} value={b}>
                    {t(`branch_${b}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={T.rank}>
              <input className="input" value={subject.rank ?? ""} onChange={(e) => set("rank", e.target.value)} maxLength={100} />
            </Field>
            <Field label={T.militaryId}>
              <input className="input" dir="ltr" value={subject.military_id ?? ""} onChange={(e) => set("military_id", e.target.value)} maxLength={64} />
            </Field>
            <Field label={T.unit}>
              <input className="input" value={subject.unit ?? ""} onChange={(e) => set("unit", e.target.value)} maxLength={200} />
            </Field>
            <Field label={T.department}>
              <input className="input" value={subject.department ?? ""} onChange={(e) => set("department", e.target.value)} maxLength={200} />
            </Field>
          </>
        )}

        {/* ---- civilian --------------------------------------------------- */}
        {subject.person_type === "CIVILIAN" && (
          <>
            <Field label={T.nationality}>
              <select
                className="select"
                value={subject.nationality_code ?? ""}
                onChange={(e) => set("nationality_code", e.target.value || null)}
                data-testid="nationality"
              >
                <option value="">{T.unknown}</option>
                {PRIORITY_COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.ar}
                  </option>
                ))}
                <option disabled>──────────</option>
                {OTHER_COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.ar}
                  </option>
                ))}
              </select>
            </Field>
            {!subject.nationality_code && (
              <Field label={T.nationalityOther}>
                <input className="input" value={subject.nationality_name ?? ""} onChange={(e) => set("nationality_name", e.target.value)} maxLength={100} />
              </Field>
            )}
            {lebanese && (
              <>
                <Field label={T.registerNumber}>
                  <input className="input" dir="ltr" value={subject.register_number ?? ""} onChange={(e) => set("register_number", e.target.value)} maxLength={64} data-testid="register-number" />
                </Field>
                <Field label={T.placeOfRegistration}>
                  <input className="input" value={subject.place_of_registration ?? ""} onChange={(e) => set("place_of_registration", e.target.value)} maxLength={200} />
                </Field>
                <label className="checkbox field">
                  <input type="checkbox" checked={subject.is_unregistered} onChange={(e) => set("is_unregistered", e.target.checked)} />
                  {T.isUnregistered}
                </label>
              </>
            )}
          </>
        )}

        {/* ---- undocumented ------------------------------------------------ */}
        <div className="field full">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={subject.is_undocumented}
              onChange={(e) => set("is_undocumented", e.target.checked)}
              data-testid="is-undocumented"
            />
            {T.isUndocumented}
          </label>
        </div>
        {subject.is_undocumented && (
          <Field label={T.undocumentedReason}>
            <select className="select" value={subject.undocumented_reason ?? ""} onChange={(e) => set("undocumented_reason", (e.target.value || null) as UndocumentedReason | null)}>
              <option value="">{T.none}</option>
              {REASONS.map((r) => (
                <option key={r} value={r}>
                  {t(`reason_${r}`)}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label={T.identityConfidence}>
          <select className="select" value={subject.identity_confidence} onChange={(e) => set("identity_confidence", e.target.value as IdentityConfidence)}>
            {CONFIDENCES.map((c) => (
              <option key={c} value={c}>
                {t(`confidence_${c}`)}
              </option>
            ))}
          </select>
        </Field>

        <Field label={T.notes} full>
          <textarea className="textarea" style={{ minHeight: 60 }} value={subject.notes ?? ""} onChange={(e) => set("notes", e.target.value)} maxLength={4000} />
        </Field>
      </div>

      {/* ---- documents ---------------------------------------------------- */}
      <div className="doc-section">
        <div className="flex between">
          <h4 className="doc-title">{T.documents}</h4>
          <button
            className="btn btn-sm"
            type="button"
            onClick={() => set("documents", [...subject.documents, emptyDocument(types[0])])}
            data-testid="add-document"
          >
            <IconPlus width={14} height={14} /> {T.addDocument}
          </button>
        </div>
        {subject.documents.length === 0 && <p className="muted small mt-8">{T.noDocuments}</p>}
        {subject.documents.map((doc, i) => (
          <DocumentRow
            key={doc.id ?? `new-${i}`}
            sessionId={sessionId}
            doc={doc}
            types={types}
            canUpload={canUploadDocuments}
            onChange={(d) => set("documents", subject.documents.map((x, idx) => (idx === i ? d : x)))}
            onRemove={() => set("documents", subject.documents.filter((_, idx) => idx !== i))}
          />
        ))}
        {(subject.duplicate_of_sessions?.length ?? 0) > 0 && (
          <div className="mt-8">
            <Alert kind="warning">
              {T.duplicateDocumentWarning} <span className="mono">{subject.duplicate_of_sessions!.join("، ")}</span>
            </Alert>
          </div>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------- read-only summary (details tab) */

export function subjectIdentitySummary(s: Subject): string {
  if (s.person_type === "MILITARY") {
    return [t("person_MILITARY"), s.security_branch ? t(`branch_${s.security_branch}`) : null, s.rank, s.military_id]
      .filter(Boolean)
      .join(" — ");
  }
  if (s.person_type === "UNKNOWN") {
    return [t("person_UNKNOWN"), s.undocumented_reason ? t(`reason_${s.undocumented_reason}`) : null].filter(Boolean).join(" — ");
  }
  const parts = [t("person_CIVILIAN")];
  if (s.nationality_code || s.nationality_name) {
    parts.push(countryName(s.nationality_code, s.nationality_name));
  }
  if (s.register_number) parts.push(`${T.registerNumber}: ${s.register_number}`);
  if (s.is_unregistered) parts.push(T.isUnregistered);
  return parts.filter(Boolean).join(" — ");
}

export function documentSummary(d: SubjectDocument): string {
  return [t(`doc_${d.document_type}`), d.document_number, d.expiry_date ? `${T.expiryDate}: ${formatDate(d.expiry_date)}` : null]
    .filter(Boolean)
    .join(" — ");
}
