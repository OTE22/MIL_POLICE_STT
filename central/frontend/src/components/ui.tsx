/* Small shared UI building blocks: toasts, modal, badges, pagination, alerts. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

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
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
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
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${size === "lg" ? "modal-lg" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
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
    <div className="loading">
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
  return (
    <div className={`field ${full ? "full" : ""}`}>
      <label>
        {label}
        {required && <span className="req">*</span>}
      </label>
      {children}
      {hint && <span className="hint">{hint}</span>}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}
