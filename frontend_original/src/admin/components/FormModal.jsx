import { useEffect, useState } from "react";

export default function FormModal({ open, title, fields = [], initial = {}, onSubmit, onClose }) {
  const [form, setForm] = useState(initial || {});
  useEffect(() => setForm(initial || {}), [initial, open]);
  if (!open) return null;
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  return (
    <div className="cms-modal-backdrop">
      <form className="cms-modal" onSubmit={(e) => { e.preventDefault(); onSubmit?.(form); }}>
        <div className="cms-modal-head"><h3>{title}</h3><button type="button" onClick={onClose}>×</button></div>
        <div className="cms-form-grid">
          {fields.map((field) => (
            <label key={field.name} className={field.type === "textarea" || field.type === "json" ? "wide" : ""}>
              <span>{field.label}</span>
              {field.type === "checkbox" ? (
                <input type="checkbox" checked={Boolean(form[field.name])} onChange={(e) => set(field.name, e.target.checked)} />
              ) : field.type === "textarea" ? (
                <textarea value={form[field.name] || ""} onChange={(e) => set(field.name, e.target.value)} rows={5} />
              ) : field.type === "select" ? (
                <select value={form[field.name] ?? ""} onChange={(e) => set(field.name, e.target.value)}>
                  <option value="">Select...</option>
                  {(field.options || []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              ) : field.type === "json" ? (
                <textarea value={typeof form[field.name] === "string" ? form[field.name] : JSON.stringify(form[field.name] || {}, null, 2)} onChange={(e) => {
                  try { set(field.name, JSON.parse(e.target.value)); } catch { set(field.name, e.target.value); }
                }} rows={6} />
              ) : (
                <input type={field.type || "text"} value={form[field.name] ?? ""} onChange={(e) => set(field.name, field.type === "number" ? Number(e.target.value) : e.target.value)} />
              )}
            </label>
          ))}
        </div>
        <div className="cms-actions right"><button type="button" className="cms-btn light" onClick={onClose}>Cancel</button><button className="cms-btn">Save</button></div>
      </form>
    </div>
  );
}
