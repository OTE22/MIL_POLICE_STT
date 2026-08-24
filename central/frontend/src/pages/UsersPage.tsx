import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, http, qs } from "@/api/client";
import type { UserRow } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Badge, Field, Loading, Modal, useToast } from "@/components/ui";
import { IconPlus } from "@/components/Icons";

const ROLES = ["ADMIN", "INVESTIGATOR", "USER"];
const ROLE_PERMISSIONS: Record<string, string[]> = {
  ADMIN: ["إدارة المستخدمين والأدوار", "عرض جميع الجلسات", "إدارة محطات العمل", "عرض سجل التدقيق", "كل صلاحيات المحقق"],
  INVESTIGATOR: ["إنشاء الجلسات", "عرض الجلسات المسندة", "التسجيل ورفع الملفات", "تشغيل المعالجة المحلية", "عرض وتصحيح النص المفرغ", "تعيين أسماء المتحدثين", "تسجيل محطة العمل"],
  USER: ["عرض الجلسات المسندة", "عرض النص المفرغ (قراءة فقط)"],
};

interface ProfileForm {
  full_name: string;
  rank: string;
  military_id: string;
  unit: string;
  department: string;
  job_title: string;
  phone: string;
  email: string;
  location: string;
}
const emptyProfile = (): ProfileForm => ({ full_name: "", rank: "", military_id: "", unit: "", department: "", job_title: "", phone: "", email: "", location: "" });
const clean = (v: string) => (v.trim() ? v.trim() : null);
const roleLabel = (r: string) => t(`role${r[0]}${r.slice(1).toLowerCase()}`, r);

function UserModal({ user, onClose, onSaved }: { user: UserRow | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<string[]>(user?.roles ?? ["INVESTIGATOR"]);
  const [mustChange, setMustChange] = useState(true);
  const [profile, setProfile] = useState<ProfileForm>(
    user?.profile
      ? {
          full_name: user.profile.full_name,
          rank: user.profile.rank ?? "",
          military_id: user.profile.military_id ?? "",
          unit: user.profile.unit ?? "",
          department: user.profile.department ?? "",
          job_title: user.profile.job_title ?? "",
          phone: user.profile.phone ?? "",
          email: user.profile.email ?? "",
          location: user.profile.location ?? "",
        }
      : emptyProfile(),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const profilePayload = {
      full_name: profile.full_name.trim(),
      rank: clean(profile.rank),
      military_id: clean(profile.military_id),
      unit: clean(profile.unit),
      department: clean(profile.department),
      job_title: clean(profile.job_title),
      phone: clean(profile.phone),
      email: clean(profile.email),
      location: clean(profile.location),
    };
    try {
      if (user) {
        await http.put(`/users/${user.id}`, { roles, profile: profilePayload });
        toast.success(T.userUpdated);
      } else {
        await http.post("/users", { username: username.trim(), password, roles, must_change_password: mustChange, profile: profilePayload });
        toast.success(T.userCreated);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  const set = (k: keyof ProfileForm) => (e: React.ChangeEvent<HTMLInputElement>) => setProfile((p) => ({ ...p, [k]: e.target.value }));

  return (
    <Modal title={user ? T.editUser : T.addUser} onClose={onClose} size="lg">
      <form onSubmit={submit}>
        {error && <div className="mb-16"><Alert kind="danger">{error}</Alert></div>}
        <div className="form-grid">
          <div className="section-title">{T.login}</div>
          <Field label={T.username} required>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} disabled={!!user} required dir="ltr" pattern="[a-zA-Z0-9._\-]{3,64}" />
          </Field>
          {!user && (
            <Field label={T.password} required hint={T.passwordPolicy}>
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} dir="ltr" autoComplete="new-password" />
            </Field>
          )}
          <Field label={T.roles} required full>
            <div className="flex wrap">
              {ROLES.map((r) => (
                <label key={r} className="checkbox">
                  <input type="checkbox" checked={roles.includes(r)} onChange={(e) => setRoles((prev) => (e.target.checked ? [...prev, r] : prev.filter((x) => x !== r)))} />
                  {roleLabel(r)}
                </label>
              ))}
            </div>
            <div className="hint">
              {roles.map((r) => (
                <div key={r}><b>{roleLabel(r)}:</b> {ROLE_PERMISSIONS[r]?.join("، ")}</div>
              ))}
            </div>
          </Field>
          {!user && (
            <label className="checkbox field full">
              <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} /> {T.mustChangePassword}
            </label>
          )}
          <div className="section-title">{T.fullName}</div>
          <Field label={T.fullName} required><input className="input" value={profile.full_name} onChange={set("full_name")} required /></Field>
          <Field label={T.rank}><input className="input" value={profile.rank} onChange={set("rank")} /></Field>
          <Field label={T.militaryId}><input className="input" value={profile.military_id} onChange={set("military_id")} dir="ltr" /></Field>
          <Field label={T.unit}><input className="input" value={profile.unit} onChange={set("unit")} /></Field>
          <Field label={T.department}><input className="input" value={profile.department} onChange={set("department")} /></Field>
          <Field label={T.jobTitle}><input className="input" value={profile.job_title} onChange={set("job_title")} /></Field>
          <Field label={T.phone}><input className="input" value={profile.phone} onChange={set("phone")} dir="ltr" /></Field>
          <Field label={T.email}><input className="input" type="email" value={profile.email} onChange={set("email")} dir="ltr" /></Field>
          <Field label={T.location}><input className="input" value={profile.location} onChange={set("location")} /></Field>
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || roles.length === 0 || !profile.full_name.trim()}>{T.save}</button>
          <button className="btn" type="button" onClick={onClose}>{T.cancel}</button>
        </div>
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }: { user: UserRow; onClose: () => void }) {
  const toast = useToast();
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pw !== confirm) return setError(T.passwordsMismatch);
    setBusy(true);
    try {
      await http.post(`/users/${user.id}/reset-password`, { new_password: pw, must_change_password: true });
      toast.success(T.passwordChanged);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`${T.resetPassword} — ${user.username}`} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="mb-16"><Alert kind="danger">{error}</Alert></div>}
        <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
          <Field label={T.newPassword} required hint={T.passwordPolicy}><input className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={10} required dir="ltr" /></Field>
          <Field label={T.confirmPassword} required><input className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required dir="ltr" /></Field>
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>{T.save}</button>
          <button className="btn" type="button" onClick={onClose}>{T.cancel}</button>
        </div>
      </form>
    </Modal>
  );
}

export function UsersPage() {
  const toast = useToast();
  const { user: me } = useAuth();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [editing, setEditing] = useState<UserRow | null | undefined>(undefined);
  const [resetFor, setResetFor] = useState<UserRow | null>(null);

  const load = useCallback(() => {
    void http.get<{ items: UserRow[] }>(`/users${qs({ q, page_size: 200 })}`).then((r) => setRows(r.items));
  }, [q]);
  useEffect(() => {
    const h = setTimeout(load, 200);
    return () => clearTimeout(h);
  }, [load]);

  const toggle = async (u: UserRow) => {
    try {
      await http.patch(`/users/${u.id}/status`, { is_active: !u.is_active });
      toast.success(T.userUpdated);
      load();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    }
  };

  return (
    <>
      <div className="page-header">
        <h1>{T.users}</h1>
        <button className="btn btn-primary" onClick={() => setEditing(null)} type="button">
          <IconPlus /> {T.addUser}
        </button>
      </div>
      <div className="card">
        <div className="toolbar">
          <input className="input search" placeholder={`${T.search}…`} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {!rows ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{T.name}</th>
                  <th>{T.username}</th>
                  <th>{T.role}</th>
                  <th>{T.rank}</th>
                  <th>{T.militaryId}</th>
                  <th>{T.status}</th>
                  <th>{T.lastLogin}</th>
                  <th>{T.actions}</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={8} className="empty">{T.noData}</td></tr>}
                {rows.map((u) => (
                  <tr key={u.id}>
                    <td>{u.profile?.full_name ?? T.none}</td>
                    <td className="ltr">{u.username}</td>
                    <td>{u.roles.map(roleLabel).join("، ")}</td>
                    <td>{u.profile?.rank ?? T.none}</td>
                    <td className="ltr">{u.profile?.military_id ?? T.none}</td>
                    <td><Badge kind={u.is_active ? "green" : "red"}>{u.is_active ? T.active : T.disabled}</Badge></td>
                    <td className="num">{formatDateTime(u.last_login_at)}</td>
                    <td className="actions-cell">
                      <div className="flex">
                        <button className="btn btn-sm" onClick={() => setEditing(u)} type="button">{T.edit}</button>
                        <button className="btn btn-sm" onClick={() => setResetFor(u)} type="button">{T.resetPassword}</button>
                        <button className="btn btn-sm" disabled={u.id === me?.id} onClick={() => void toggle(u)} type="button">{u.is_active ? T.disableUser : T.enableUser}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editing !== undefined && <UserModal user={editing} onClose={() => setEditing(undefined)} onSaved={load} />}
      {resetFor && <ResetPasswordModal user={resetFor} onClose={() => setResetFor(null)} />}
    </>
  );
}
