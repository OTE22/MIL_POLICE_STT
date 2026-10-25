/* Small shared UI building blocks: toasts, modal, badges, pagination, alerts. */
import { Children, cloneElement, isValidElement, createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode, type ReactElement } from "react";

import { T, t } from "@/lib/i18n";
import type { JobStatus, SessionStatus } from "@/api/types";
import { IconAlert, IconCheck, IconInfo, IconX } from "./Icons";

/* ---------------------------------------------------------------- toasts */
type ToastKind = "info" | "success" | "error" | "warning";
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}
interface ToastApi {
  push: (text: string, kind?: ToastKind) => void;
  success: (text: string) => void;
  error: (text: string) => void;
  warning: (text: string) => void;
}
const ToastCtx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, kind, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), Math.min(20000, Math.max(kind === "error" ? 12000 : 8000, text.length * 70)));
  }, []);
  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (x) => push(x, "success"),
      error: (x) => push(x, "error"),
      warning: (x) => push(x, "warning"),
    }),
    [push],
  );
  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((x) => (
          <div key={x.id} className={`toast toast-${x.kind}`}>
            {x.kind === "success" ? <IconCheck /> : x.kind === "error" ? <IconAlert /> : <IconInfo />}
            <span>{x.text}</span>
            <button className="icon-btn" type="button" aria-label="إغلاق الإشعار" onClick={() => setToasts(prev => prev.filter(toast => toast.id !== x.id))}><IconX /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("ToastProvider missing");
  return ctx;
}

/* ----------------------------------------------------------------- modal */
export function Modal({
  title,
  onClose,
  children,
  footer,
  size,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "lg";
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      // Only the topmost modal handles keyboard input when dialogs are nested.
      const dialogs = document.querySelectorAll('[role="dialog"]');
      if (dialogs[dialogs.length - 1] !== dialog.current) return;
      if (e.key === "Escape") { e.preventDefault(); close.current(); }
      if (e.key !== "Tab") return;
      const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? []).filter(el => el.getClientRects().length && !el.closest('[inert]'));
      const first = items[0], last = items[items.length - 1];
      if (!first) { e.preventDefault(); dialog.current?.focus(); }
      else if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialog} tabIndex={-1} className={`modal ${size === "lg" ? "modal-lg" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label={T.close} type="button">
            <IconX />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- badges */
const SESSION_BADGE: Record<SessionStatus, string> = {
  DRAFT: "badge-gray",
  RECORDING: "badge-red",
  PROCESSING: "badge-blue",
  COMPLETED: "badge-green",
  FAILED: "badge-red",
  ARCHIVED: "badge-navy",
};
export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  return <span className={`badge ${SESSION_BADGE[status] ?? "badge-gray"}`}>{t(`status_${status}`)}</span>;
}
const JOB_BADGE: Record<JobStatus, string> = {
  REQUESTED: "badge-gray",
  ACCEPTED: "badge-blue",
  PROCESSING: "badge-blue",
  COMPLETED: "badge-green",
  FAILED: "badge-red",
  CANCELLED: "badge-amber",
};
export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <span className={`badge ${JOB_BADGE[status] ?? "badge-gray"}`}>{t(`job_${status}`)}</span>;
}
export function Badge({ kind, children }: { kind: "gray" | "blue" | "green" | "amber" | "red" | "navy"; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>;
}

/* ------------------------------------------------------------------ alert */
export function Alert({ kind, children }: { kind: "info" | "warning" | "danger" | "success"; children: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === "danger" ? "alert" : undefined}>
      {kind === "danger" || kind === "warning" ? <IconAlert /> : kind === "success" ? <IconCheck /> : <IconInfo />}
      <div>{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------- pagination */
export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pagination">
      <span>
        {T.total}: <span className="num">{total}</span> — {T.page} <span className="num">{page}</span> {T.of}{" "}
        <span className="num">{pages}</span>
      </span>
      <div className="pages">
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)} type="button">
          {T.previous}
        </button>
        <button className="btn btn-sm" disabled={page >= pages} onClick={() => onChange(page + 1)} type="button">
          {T.next}
        </button>
      </div>
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" /> {T.loading}
    </div>
  );
}

export function Field({
  label,
  required,
  children,
  full,
  hint,
  error,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
  full?: boolean;
  hint?: string;
  error?: string;
}) {
  const id = useId();
  const items = Children.toArray(children);
  const control = items.find(child => isValidElement(child) && typeof child.type === "string" && ["input", "select", "textarea"].includes(child.type)) as ReactElement<Record<string, unknown>> | undefined;
  const controlId = String(control?.props.id || `${id}-control`);
  const describedBy = [control?.props["aria-describedby"], hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`field ${full ? "full" : ""}`} role={control ? undefined : "group"} aria-labelledby={control ? undefined : `${id}-label`}>
      <label id={`${id}-label`} htmlFor={control ? controlId : undefined}>
        {label}
        {required && <span className="req">*</span>}
      </label>
      {items.map(child => child === control ? cloneElement(control, { id: controlId, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined, "aria-required": required || undefined }) : child)}
      {hint && <span id={`${id}-hint`} className="hint">{hint}</span>}
      {error && <span id={`${id}-error`} className="error-text">{error}</span>}
    </div>
  );
}
