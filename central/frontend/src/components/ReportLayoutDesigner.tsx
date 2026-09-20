import { useEffect, useRef, useState } from "react";
import { ApiError, downloadFile, http } from "@/api/client";
import type { ReportTemplateList } from "@/api/types";
import { Alert } from "@/components/ui";
import { errorMessage } from "@/lib/i18n";
import "@/styles/report-layout.css";
import { clamp, fractionToMm, mmToFraction, ptToMm, moveBox, resizeBox, setDimensionMm, overlappingPairs } from "@/lib/report-layout-geometry";
import type { Box, Page, Handle, Guides } from "@/lib/report-layout-geometry";

type Layout = { name: string; pages: Page[] };
const fields: Record<string, string> = {
  report_number: "رقم المحضر", case_subject: "موضوع القضية", report_date: "تاريخ المحضر", report_time: "وقت المحضر",
  report_datetime: "التاريخ والوقت", investigation_location: "مكان التحقيق", session_number: "رقم الجلسة",
  session_title: "عنوان الجلسة", session_date: "تاريخ الجلسة", session_status: "حالة الجلسة",
  investigator_name: "اسم المحقق", investigator_rank: "رتبة المحقق", investigator_unit: "وحدة المحقق",
  subject_name: "اسم المستمع إليه", subject_rank: "رتبته", subject_person_type: "صفته", subject_nationality: "جنسيته",
  generated_at: "تاريخ الإصدار", generated_by_name: "اسم مُصدر المحضر", report_version: "نسخة المحضر",
  template_version: "نسخة القالب", recording_count: "عدد التسجيلات", qa_count: "عدد الأسئلة",
};

const imageUrl = (page: Page) => `data:image/${page.image.startsWith('/9j/') ? 'jpeg' : 'png'};base64,${page.image}`;
const MAX_PAGES = 30;

function MillimetreInput({ value, min, max, onCommit }: { value:number; min:number; max:number; onCommit:(value:number)=>void }) {
  min=Math.min(min,max);
  const [text,setText]=useState(String(value));
  useEffect(() => setText(String(value)),[value]);
  return <input type="number" className="input" min={min} max={max} step={.1} value={text}
    onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur(); } }}
    onBlur={() => { const n=Number(text); if (!text.trim() || !Number.isFinite(n)) { setText(String(value)); return; } const bounded=clamp(n,min,max); setText(String(Number(bounded.toFixed(1)))); onCommit(bounded); }} />;
}

export function ReportLayoutDesigner({ onSaved, editId, onDirtyChange, deletedTemplateId }: { onSaved: () => void; editId?: string; onDirtyChange?: (dirty: boolean) => void; deletedTemplateId?: string }) {
  const [layout, setLayout] = useState<Layout>({ name: "قالب محضر التحقيق", pages: [] });
  const [history, setHistory] = useState<Layout[]>([]);
  const [future, setFuture] = useState<Layout[]>([]);
  const [mode, setMode] = useState<'select'|'draw'>('select');
  const [snap, setSnap] = useState(true);
  const [gridMm, setGridMm] = useState(5);
  const [showGrid, setShowGrid] = useState(false);
  const [guides, setGuides] = useState<Guides>({});
  const [expanded, setExpanded] = useState(false);
  const [fieldSearch, setFieldSearch] = useState('');
  const [pageIndex, setPageIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [field, setField] = useState("report_number");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Box | null>(null);
  const [zoom, setZoom] = useState(100);
  const surface = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const zoomFocus = useRef<{ x:number; y:number } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const gesture = useRef<{ x: number; y: number; index?: number; box?: Box; handle?: Handle; before: Layout; changed?: boolean } | null>(null);
  const draftRef = useRef<Box | null>(null);
  const page = layout.pages[pageIndex];
  const chosen = selected === null ? null : page?.boxes[selected];
  const changeZoom = (value: number) => {
    const view=viewport.current, paper=surface.current;
    if (view && paper) zoomFocus.current=chosen ? {x:chosen.x+chosen.width/2,y:chosen.y+chosen.height/2} : {x:(view.scrollLeft+view.clientWidth/2-32)/paper.clientWidth,y:(view.scrollTop+view.clientHeight/2-32)/paper.clientHeight};
    setZoom(value);
  };
  useEffect(() => {
    const view=viewport.current, paper=surface.current, center=zoomFocus.current;
    if (view && paper && center) {
      view.scrollLeft=32+center.x*paper.clientWidth-view.clientWidth/2;
      view.scrollTop=32+center.y*paper.clientHeight-view.clientHeight/2;
    }
    zoomFocus.current=null;
  },[zoom]);
  const fail = (err: unknown) => setError(err instanceof ApiError ? errorMessage(err.code) : "تعذر إتمام العملية. تحقق من حجم النموذج وحاول مجدداً.");
  useEffect(() => { if (editId) void load(); }, [editId]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (savedId && deletedTemplateId === savedId) { setSavedId(null); setDirty(true); }
  }, [deletedTemplateId, savedId]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const checkpoint = (before = layout) => { setHistory(old => [...old.slice(-49), before]); setFuture([]); };
  const update = (next: Layout, remember = true) => {
    if (remember) checkpoint();
    setLayout(next); setDirty(true); setSavedId(null);
  };
  const changeBoxes = (fn: (boxes: Box[]) => Box[], remember = true) => {
    update({ ...layout, pages: layout.pages.map((p, i) => i === pageIndex ? { ...p, boxes: fn(p.boxes) } : p) }, remember);
  };
  const go = (index: number) => { setPageIndex(index); setSelected(null); setDraft(null); draftRef.current=null; setGuides({}); gesture.current = null; };
  const undo = () => {
    if (!history.length || busy) return;
    const previous=history[history.length-1]; setFuture(old => [...old,layout]); setLayout(previous); setHistory(history.slice(0,-1));
    setDirty(true); setSavedId(null); go(Math.min(pageIndex,Math.max(0,previous.pages.length-1)));
  };
  const redo = () => {
    if (!future.length || busy) return;
    const next=future[future.length-1]; setHistory(old => [...old,layout]); setLayout(next); setFuture(future.slice(0,-1));
    setDirty(true); setSavedId(null); go(Math.min(pageIndex,Math.max(0,next.pages.length-1)));
  };
  const editChosen = (fn: (box: Box) => Box) => changeBoxes(boxes => boxes.map((box,i) => i === selected ? fn(box) : box));
  const duplicate = () => {
    if (!chosen || page.boxes.length >= 60) return;
    changeBoxes(boxes => [...boxes,moveBox(chosen,mmToFraction(3,page.width_pt),mmToFraction(3,page.height_pt),page,[],{ snap:false,gridMm:0,toleranceX:0,toleranceY:0 }).box]);
    setSelected(page.boxes.length);
  };
  const keyboard = (e: React.KeyboardEvent) => {
    if (busy || (e.target as HTMLElement).closest('input,select,textarea,[contenteditable="true"]')) return;
    if (e.key === 'Escape') { setSelected(null); setMode('select'); setExpanded(false); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (!chosen || !(e.target as HTMLElement).closest('.layout-paper')) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicate(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); changeBoxes(boxes => boxes.filter((_,i) => i !== selected)); setSelected(null); return; }
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
    e.preventDefault();
    const amount=e.shiftKey ? 5 : .5;
    const dx=mmToFraction(e.key === 'ArrowLeft' ? -amount : e.key === 'ArrowRight' ? amount : 0,page.width_pt);
    const dy=mmToFraction(e.key === 'ArrowUp' ? -amount : e.key === 'ArrowDown' ? amount : 0,page.height_pt);
    editChosen(box => moveBox(box,dx,dy,page,[],{ snap:false,gridMm:0,toleranceX:0,toleranceY:0 }).box);
  };
  const point = (e: React.PointerEvent) => {
    const rect = surface.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - rect.left) / rect.width, 0, 1), y: clamp((e.clientY - rect.top) / rect.height, 0, 1) };
  };
  const load = async (file?: File) => {
    if (file && file.size > 12 * 1024 * 1024) { setError("حجم الملف يتجاوز ١٢ ميغابايت."); return; }
    setBusy(true); setError(null);
    try {
      if (file) {
        const result = await http.upload<{ pages: Page[] }>("/report-templates/sample", file);
        const pages = [...layout.pages, ...result.pages];
        if (pages.length > MAX_PAGES) { setError("يمكن للقالب أن يحتوي على ٣٠ صفحة كحد أقصى."); return; }
        if (pages.reduce((sum, p) => sum + p.image.length, 0) > 8 * 1024 * 1024 * 4 / 3) { setError("صور الصفحات كبيرة جداً. استخدم نموذجاً أقل دقة أو احذف صفحات غير ضرورية."); return; }
        update({ name: layout.pages.length ? layout.name : file.name.replace(/\.[^.]+$/, "").slice(0,150), pages });
        go(layout.pages.length);
      } else {
        const next = await http.get<Layout>(`/report-templates/${editId}/layout`);
        setLayout(next); setHistory([]); setFuture([]); setDirty(false); go(0); setSavedId(editId || null);
      }
    } catch (err) { fail(err); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const result = await http.post<ReportTemplateList>("/report-templates/layout", layout);
      setSavedId(result.versions[0].id); setDirty(false); onSaved();
    } catch (err) { fail(err); } finally { setBusy(false); }
  };
  const movePage = (delta: number) => {
    const pages = [...layout.pages]; const target = pageIndex + delta;
    [pages[pageIndex], pages[target]] = [pages[target], pages[pageIndex]];
    update({ ...layout, pages }); go(target);
  };
  const addBox = () => {
    changeBoxes(boxes => [...boxes, { field, x: .55, y: .15, width: .35, height: .07, font_size: 12 }]);
    setSelected(page.boxes.length);
  };
  const overlaps = page ? overlappingPairs(page.boxes) : [];
  const fieldOptions = Object.entries(fields).filter(([key,label]) => key === field || label.includes(fieldSearch.trim()));
  return <section className={`card layout-designer ${expanded ? 'layout-expanded' : ''}`} onKeyDown={keyboard} data-testid="report-layout-designer" aria-label="مصمم قالب المحضر">
    <header className="layout-heading">
      <div><h2>مصمم قالب المحضر</h2><p className="muted">ضع الحقول على نموذجك، ثم راجع المعاينة قبل التفعيل.</p></div>
      <span className={`badge ${dirty ? 'badge-amber' : 'badge-gray'}`}>{busy ? "جارٍ المعالجة…" : dirty ? "تغييرات غير محفوظة" : savedId ? "محفوظ" : "قالب جديد"}</span>
    </header>
    <ol className="layout-steps"><li className={!page ? 'current' : ''}>١. رفع النموذج</li><li className={page && !savedId ? 'current' : ''}>٢. توزيع الحقول</li><li className={savedId ? 'current' : ''}>٣. المعاينة والتفعيل</li></ol>
    {error && <Alert kind="danger">{error}</Alert>}
    <input ref={fileInput} type="file" accept="application/pdf,image/png,image/jpeg" hidden disabled={busy}
      onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void load(file); }} />
    {!page ? <div className="layout-empty">
      <span className="layout-empty-icon" aria-hidden="true">▤</span><h3>ابدأ بنموذج المحضر الخاص بك</h3>
      <p className="muted">PDF متعدد الصفحات أو صورة PNG / JPEG · حتى ٣٠ صفحة · ١٢ ميغابايت لكل ملف</p>
      <button className="btn btn-primary" disabled={busy} onClick={() => fileInput.current?.click()}>{busy ? "جارٍ تحميل الصفحات…" : "اختيار نموذج من الجهاز"}</button>
      <p className="small muted">استخدم نموذجاً فارغاً. يمكنك إضافة ملفات أخرى وترتيب صفحاتها لاحقاً.</p>
    </div> : <>
      <fieldset disabled={busy} className="layout-controls">
        <div className="layout-toolbar">
          <label className="layout-name">اسم القالب<input className="input" value={layout.name} maxLength={150} onChange={e => update({ ...layout, name: e.target.value })} /></label>
          <button className="btn" disabled={!history.length} title="Ctrl+Z" onClick={undo}>تراجع</button>
          <button className="btn" disabled={!future.length} title="Ctrl+Shift+Z" onClick={redo}>إعادة</button>
          <button className="btn" aria-pressed={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'تصغير مساحة العمل' : 'توسيع مساحة العمل'}</button>
          <button className="btn" disabled={layout.pages.length >= MAX_PAGES} onClick={() => fileInput.current?.click()}>＋ إضافة صفحات</button>
        </div>
        <div className="layout-workspace">
          <nav className="layout-pages" aria-label="صفحات النموذج">
            <strong>الصفحات <span className="muted">({layout.pages.length})</span></strong>
            <div className="layout-thumbnails">{layout.pages.map((p,i) => <button className={`layout-thumbnail ${pageIndex === i ? 'selected' : ''}`} key={i} aria-current={pageIndex === i ? 'page' : undefined} onClick={() => go(i)}>
              <img loading="lazy" src={imageUrl(p)} alt={`الصفحة ${i+1}`} /><span>صفحة {i+1}</span><small>{p.boxes.length ? `${p.boxes.length} حقول` : "بدون حقول"}</small>
            </button>)}</div>
          </nav>
          <div className="layout-stage">
            <div className="layout-canvas-toolbar">
              <button className="btn btn-sm" disabled={pageIndex === 0} onClick={() => go(pageIndex-1)}>السابقة</button>
              <label>صفحة <select className="select" aria-label="انتقل إلى الصفحة" value={pageIndex} onChange={e => go(Number(e.target.value))}>{layout.pages.map((_,i) => <option key={i} value={i}>{i+1} / {layout.pages.length}</option>)}</select></label>
              <button className="btn btn-sm" disabled={pageIndex === layout.pages.length-1} onClick={() => go(pageIndex+1)}>التالية</button>
              <select className="select" aria-label="تكبير الصفحة" value={zoom} onChange={e => changeZoom(Number(e.target.value))}><option value={100}>ملاءمة العرض</option><option value={125}>١٢٥٪</option><option value={150}>١٥٠٪</option><option value={200}>٢٠٠٪</option><option value={300}>٣٠٠٪</option><option value={400}>٤٠٠٪</option></select>
            </div>
            <div className="layout-precision-toolbar">
              <div className="layout-mode" role="group" aria-label="أداة التحرير"><button className="btn btn-sm" aria-pressed={mode === 'select'} onClick={() => setMode('select')}>تحديد وتحريك</button><button className="btn btn-sm" aria-pressed={mode === 'draw'} onClick={() => setMode('draw')}>رسم حقل</button></div>
              <label><input type="checkbox" checked={snap} onChange={e => setSnap(e.target.checked)} />محاذاة تلقائية</label>
              <label><input type="checkbox" checked={showGrid} onChange={e => setShowGrid(e.target.checked)} />شبكة</label>
              <label>الشبكة<select className="select" value={gridMm} onChange={e => setGridMm(Number(e.target.value))}>{[1,2,5,10].map(n => <option key={n} value={n}>{n} مم</option>)}</select></label>
            </div>
            <p className="layout-measure-note">{ptToMm(page.width_pt).toFixed(1)} × {ptToMm(page.height_pt).toFixed(1)} مم · القياس من أعلى يسار الصفحة · Alt لتعطيل المحاذاة أثناء السحب</p>
            <div ref={viewport} className="layout-canvas-scroll" dir="ltr">
              <div className="layout-sheet" style={{ width: `${zoom}%` }}>
                <div className="layout-ruler layout-ruler-x" aria-hidden="true">{Array.from({ length:Math.floor(ptToMm(page.width_pt)/10)+1 },(_,i) => <span key={i} style={{ left:`${mmToFraction(i*10,page.width_pt)*100}%` }}>{i*10}</span>)}</div>
                <div className="layout-ruler layout-ruler-y" aria-hidden="true">{Array.from({ length:Math.floor(ptToMm(page.height_pt)/10)+1 },(_,i) => <span key={i} style={{ top:`${mmToFraction(i*10,page.height_pt)*100}%` }}>{i*10}</span>)}</div>
              <div ref={surface} tabIndex={0} aria-label="مساحة وضع الحقول؛ استخدم الأسهم لتحريك الحقل المحدد" className={`layout-paper layout-tool-${mode}`} style={{ width:'100%',aspectRatio: `${page.width_pt}/${page.height_pt}` }}
                onPointerDown={e => { if (busy || e.button !== 0) return; surface.current!.focus(); setSelected(null); if (mode !== 'draw' || page.boxes.length >= 60) return; surface.current!.setPointerCapture(e.pointerId); const start=point(e); if (snap && showGrid && !e.altKey) { start.x=clamp(Math.round(start.x/mmToFraction(gridMm,page.width_pt))*mmToFraction(gridMm,page.width_pt),0,1); start.y=clamp(Math.round(start.y/mmToFraction(gridMm,page.height_pt))*mmToFraction(gridMm,page.height_pt),0,1); } gesture.current = { ...start,before:layout }; }}
                onPointerMove={e => {
                  const start = gesture.current; if (!start) return; const pos = point(e);
                  if (!start.changed && !draftRef.current && Math.abs(pos.x-start.x)+Math.abs(pos.y-start.y) < .0001) return;
                  if (start.index !== undefined && start.box) {
                    if (!start.changed) { checkpoint(start.before); start.changed=true; }
                    const rect=surface.current!.getBoundingClientRect();
                    const options={ snap:snap && !e.altKey,gridMm:showGrid ? gridMm : 0,toleranceX:6/rect.width,toleranceY:6/rect.height };
                    const others=page.boxes.filter((_,i) => i !== start.index);
                    const result=start.handle ? resizeBox(start.box,start.handle,pos.x-start.x,pos.y-start.y,page,others,options) : moveBox(start.box,pos.x-start.x,pos.y-start.y,page,others,options);
                    setGuides(result.guides); changeBoxes(boxes => boxes.map((b,i) => i === start.index ? result.box : b),false);
                  } else {
                    if (snap && showGrid && !e.altKey) { pos.x=clamp(Math.round(pos.x/mmToFraction(gridMm,page.width_pt))*mmToFraction(gridMm,page.width_pt),0,1); pos.y=clamp(Math.round(pos.y/mmToFraction(gridMm,page.height_pt))*mmToFraction(gridMm,page.height_pt),0,1); }
                    const next={ field, x: Math.min(start.x,pos.x), y: Math.min(start.y,pos.y), width: Math.abs(pos.x-start.x), height: Math.abs(pos.y-start.y), font_size: 12 };
                    draftRef.current=next; setDraft(next);
                  }
                }}
                onPointerUp={() => { const next=draftRef.current; if (gesture.current && gesture.current.index === undefined && next && next.width >= mmToFraction(2,page.width_pt) && next.height >= mmToFraction(2,page.height_pt)) { changeBoxes(boxes => [...boxes,next]); setSelected(page.boxes.length); setMode('select'); } gesture.current=null; draftRef.current=null; setDraft(null); setGuides({}); }}
                onPointerCancel={() => { const start=gesture.current; if (start?.changed) { setLayout(start.before); setHistory(old => old.slice(0,-1)); } gesture.current=null; draftRef.current=null; setDraft(null); setGuides({}); }}>
                <img src={imageUrl(page)} alt={`نموذج الصفحة ${pageIndex+1}`} draggable={false} />
                {showGrid && <div className="layout-grid" style={{ backgroundSize:`${mmToFraction(gridMm,page.width_pt)*100}% ${mmToFraction(gridMm,page.height_pt)*100}%` }} />}
                {[...page.boxes, ...(draft ? [draft] : [])].map((box,index) => <div key={index} className={`layout-box ${selected === index ? 'selected' : ''}`} style={{ left: `${box.x*100}%`, top: `${box.y*100}%`, width: `${box.width*100}%`, height: `${box.height*100}%` }}>
                  <button type="button" aria-label={`تحديد ${fields[box.field] || box.field}`} onClick={() => setSelected(index)} onPointerDown={e => { e.stopPropagation(); if (busy || e.button !== 0) return; surface.current!.focus(); surface.current!.setPointerCapture(e.pointerId); setSelected(index); gesture.current = { ...point(e),index,box:{ ...box },before:layout }; }}>{fields[box.field] || box.field}</button>
                  {selected === index && (['n','ne','e','se','s','sw','w','nw'] as Handle[]).map(handle => <button key={handle} className={`layout-resize layout-handle-${handle}`} tabIndex={-1} aria-label={`تغيير حجم المربع ${handle}`} onPointerDown={e => { e.stopPropagation(); if (busy || e.button !== 0) return; surface.current!.focus(); surface.current!.setPointerCapture(e.pointerId); gesture.current = { ...point(e),index,box:{ ...box },handle,before:layout }; }} />)}
                </div>)}
                {guides.x !== undefined && <div className="layout-guide-x" style={{ left:`${guides.x*100}%` }} />}
                {guides.y !== undefined && <div className="layout-guide-y" style={{ top:`${guides.y*100}%` }} />}
              </div>
              </div>
            </div>
            <div className="layout-page-actions"><button className="btn btn-sm" disabled={pageIndex === 0} onClick={() => movePage(-1)}>نقل للأمام</button><button className="btn btn-sm" disabled={pageIndex === layout.pages.length-1} onClick={() => movePage(1)}>نقل للخلف</button><button className="btn btn-sm btn-danger" disabled={layout.pages.length === 1} onClick={() => { update({ ...layout,pages:layout.pages.filter((_,i) => i !== pageIndex) }); go(Math.max(0,pageIndex-1)); }}>حذف الصفحة</button></div>
          </div>
          <aside className="layout-inspector">
            <h3>إضافة حقل</h3>
            <input className="input" type="search" aria-label="بحث عن حقل" placeholder="ابحث عن حقل…" value={fieldSearch} onChange={e => setFieldSearch(e.target.value)} />
            <label>اختر الحقل<select className="select" value={field} onChange={e => setField(e.target.value)}>{fieldOptions.map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <button className="btn btn-primary" disabled={page.boxes.length >= 60} onClick={addBox}>＋ وضع الحقل على الصفحة</button>
            <p className="muted small">اختر «رسم حقل» للرسم، أو أضفه بالزر. الأسهم تحرّكه ٠٫٥ مم، ومع Shift بمقدار ٥ مم.</p>
            {!!overlaps.length && <div className="layout-overlap-note">تنبيه: توجد حقول متداخلة. {overlaps.slice(0,3).map(([a,b]) => <button key={`${a}-${b}`} className="btn btn-sm" onClick={() => setSelected(a)}>{a+1} ↔ {b+1}</button>)}</div>}
            <h3>حقول الصفحة ({page.boxes.length}/60)</h3>
            <div className="layout-field-list">{!page.boxes.length && <p className="muted small">لم تُضف حقولاً إلى هذه الصفحة بعد.</p>}{page.boxes.map((box,i) => <button key={i} className={selected === i ? 'selected' : ''} onClick={() => setSelected(i)}>{i+1}. {fields[box.field] || box.field}</button>)}</div>
            {chosen && selected !== null && <div className="layout-properties">
              <h3>خصائص الحقل المحدد</h3>
              <label>الحقل<select className="select" value={chosen.field} onChange={e => changeBoxes(boxes => boxes.map((b,i) => i === selected ? { ...b,field:e.target.value } : b))}>{Object.entries(fields).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              <label>حجم الخط<input className="input" type="number" min={8} max={24} value={chosen.font_size} onChange={e => changeBoxes(boxes => boxes.map((b,i) => i === selected ? { ...b,font_size:clamp(Number(e.target.value),8,24) } : b))} /></label>
              <div><strong>الموضع والحجم بالملليمتر</strong><div className="layout-dimensions">{([['x','من اليسار'],['y','من الأعلى'],['width','العرض'],['height','الارتفاع']] as const).map(([key,label]) => <label key={key}>{label} (مم)<MillimetreInput key={`${pageIndex}-${selected}-${key}`} min={key === 'width' || key === 'height' ? 2 : 0} max={fractionToMm(key === 'x' ? 1-chosen.width : key === 'y' ? 1-chosen.height : key === 'width' ? 1-chosen.x : 1-chosen.y,key === 'x' || key === 'width' ? page.width_pt : page.height_pt)} value={Number(fractionToMm(chosen[key],key === 'x' || key === 'width' ? page.width_pt : page.height_pt).toFixed(1))} onCommit={value => editChosen(box => setDimensionMm(box,key,value,page))} /></label>)}</div></div>
              <div className="layout-align"><strong>محاذاة إلى الصفحة</strong><div className="flex gap wrap">{(['left','center','right','top','middle','bottom'] as const).map((alignment,i) => <button key={alignment} className="btn btn-sm" onClick={() => editChosen(box => ({ ...box,...(alignment === 'left' ? {x:0} : alignment === 'center' ? {x:(1-box.width)/2} : alignment === 'right' ? {x:1-box.width} : alignment === 'top' ? {y:0} : alignment === 'middle' ? {y:(1-box.height)/2} : {y:1-box.height}) }))}>{['يسار','وسط أفقي','يمين','أعلى','وسط عمودي','أسفل'][i]}</button>)}</div></div>
              <button className="btn btn-sm" disabled={page.boxes.length >= 60} onClick={duplicate}>نسخ الحقل في الصفحة</button>
              <button className="btn btn-sm" disabled={layout.pages.length < 2 || layout.pages.some(p => p.boxes.length >= 60 && !p.boxes.some(b => b.field === chosen.field))} onClick={() => update({ ...layout,pages:layout.pages.map((p,i) => i === pageIndex || p.boxes.some(b => b.field === chosen.field) ? p : { ...p,boxes:[...p.boxes,{ ...chosen }] }) })}>تكرار الحقل على باقي الصفحات</button>
              <p className="muted small">يُضاف في الموضع النسبي نفسه إلى الصفحات التي لا تحتوي على هذا الحقل.</p>
              <button className="btn btn-sm btn-danger" onClick={() => { changeBoxes(boxes => boxes.filter((_,i) => i !== selected)); setSelected(null); }}>حذف الحقل</button>
            </div>}
          </aside>
        </div>
      </fieldset>
      <footer className="layout-footer"><div><strong>{layout.pages.length} صفحات · {layout.pages.reduce((sum,p) => sum+p.boxes.length,0)} حقول</strong><p className="muted small">الأسئلة والأجوبة والمقدمة والخاتمة تتدفق تلقائياً في صفحات تالية.</p></div><div className="flex gap wrap">
        <button className="btn btn-primary" disabled={busy || !dirty || !layout.name.trim() || !layout.pages.some(p => p.boxes.length)} onClick={() => void save()}>{busy ? "جارٍ المعالجة…" : "حفظ نسخة جديدة"}</button>
        <button className="btn" disabled={busy || !savedId} onClick={() => void downloadFile(`/report-templates/${savedId}/preview`,"template-preview.docx").catch(fail)}>معاينة Word</button>
      </div></footer>
      {savedId && <Alert kind="info">النسخة محفوظة. راجع معاينة Word، ثم فعّل النسخة المطلوبة من سجل القوالب أدناه.</Alert>}
      <details className="layout-help"><summary>كيف تظهر الحقول في المحضر؟</summary><p>تُطبع صورة كل صفحة كما هي. تغطي مربعات الحقول باللون الأبيض ما تحتها؛ استخدم نموذجاً فارغاً. الصفحات بدون حقول تبقى ضمن المحضر. راجع مواضع النصوص في معاينة Word قبل التفعيل.</p></details>
      <details className="layout-help"><summary>أدوات الدقة واختصارات لوحة المفاتيح</summary><p>الخطوط الوردية تشير إلى محاذاة الحقل مع حواف أو مراكز الحقول الأخرى أو الصفحة. الشبكة والمسطرة لا تظهران في الملف النهائي. عند تحديد حقل على الصفحة: الأسهم للتحريك ٠٫٥ مم، Shift مع الأسهم للتحريك ٥ مم، Ctrl+D للنسخ، Delete للحذف. Ctrl+Z للتراجع وCtrl+Shift+Z للإعادة. يمكن تعديل الأبعاد مباشرة بالملليمتر ثم الضغط على Enter. التكبير نسبي لمساحة العمل؛ موضع الحقل المطبوع لا يتغير معه.</p></details>
    </>}
  </section>;
}
