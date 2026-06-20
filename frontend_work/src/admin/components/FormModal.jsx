import { useEffect, useState } from "react";

function OrderedMultiSelect({ value = [], options = [], onChange }) {
  const selected = Array.isArray(value) ? value.map(Number).filter(Boolean) : [];
  const optionById = new Map(options.map((option) => [Number(option.value), option]));
  const add = (artistId) => {
    const id = Number(artistId);
    if (id && !selected.includes(id)) onChange([...selected, id]);
  };
  const move = (index, direction) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= selected.length) return;
    const next = [...selected];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    onChange(next);
  };
  return (
    <div className="cms-credit-picker">
      <select value="" onChange={(event) => add(event.target.value)}>
        <option value="">Add artist...</option>
        {options.filter((option) => !selected.includes(Number(option.value))).map((option) => (
          <option key={option.value} value={option.value}>{option.label}{option.country_code ? ` (${option.country_code})` : ""}</option>
        ))}
      </select>
      <div className="cms-credit-list">
        {selected.map((artistId, index) => {
          const option = optionById.get(artistId);
          return (
            <div key={artistId} className="cms-credit-item">
              <b>{index + 1}. {option?.label || `Artist #${artistId}`}</b>
              <span>
                <button type="button" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move artist up">↑</button>
                <button type="button" onClick={() => move(index, 1)} disabled={index === selected.length - 1} aria-label="Move artist down">↓</button>
                <button type="button" onClick={() => onChange(selected.filter((id) => id !== artistId))} aria-label="Remove artist">×</button>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

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
            <label key={field.name} className={["textarea", "json", "ordered-multiselect"].includes(field.type) ? "wide" : ""}>
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
              ) : field.type === "ordered-multiselect" ? (
                <OrderedMultiSelect value={form[field.name]} options={field.options || []} onChange={(value) => set(field.name, value)} />
              ) : field.type === "json" ? (
                <textarea value={typeof form[field.name] === "string" ? form[field.name] : JSON.stringify(form[field.name] || {}, null, 2)} onChange={(e) => {
                  try { set(field.name, JSON.parse(e.target.value)); } catch { set(field.name, e.target.value); }
                }} rows={6} />
              ) : (
                <input type={field.type || "text"} value={form[field.name] ?? ""} onChange={(e) => set(field.name, field.type === "number" ? Number(e.target.value) : e.target.value)} />
              )}
              {field.help && <small className="cms-help">{field.help}</small>}
            </label>
          ))}
        </div>
        <div className="cms-actions right"><button type="button" className="cms-btn light" onClick={onClose}>Cancel</button><button className="cms-btn">Save</button></div>
      </form>
    </div>
  );
}
