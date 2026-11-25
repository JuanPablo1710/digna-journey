import { formatMexicoDateTime } from "./mexicoTime";

const relationships = {
  hijo_a: "Mi hijo o hija",
  madre_padre: "Mi madre o padre",
  pareja: "Mi pareja",
  otro: "Otra persona",
};

export function StudyOptions({ studies, studyId, onSelect }) {
  return (
    <div className="mt-6 grid gap-3">
      {studies.map((study) => (
        <label key={study.id} className={`option-card ${studyId === study.id ? "option-card-selected" : ""}`}>
          <input className="h-4 w-4 accent-primary" type="radio" name="study" value={study.id} checked={studyId === study.id} onChange={() => onSelect(study.id)} />
          <span className="flex-1"><strong>{study.name}</strong><small className="mt-1 block text-muted">{study.preparation}</small></span>
          <strong>${study.price} MXN</strong>
        </label>
      ))}
    </div>
  );
}

export function PatientFields({ form, onChange }) {
  return (
    <>
      <fieldset className="sm:col-span-2">
        <legend className="text-sm font-semibold">¿Para quién es el estudio?</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          <label className="booking-radio"><input className="mr-2 accent-primary" type="radio" name="forWhom" value="self" checked={form.forWhom === "self"} onChange={onChange} />Para mí</label>
          <label className="booking-radio"><input className="mr-2 accent-primary" type="radio" name="forWhom" value="other" checked={form.forWhom === "other"} onChange={onChange} />Para otra persona</label>
        </div>
      </fieldset>
      {form.forWhom === "other" && (
        <>
          <p className="text-sm text-muted sm:col-span-2">Aviso de privacidad simulado. Los datos del paciente se usan para gestionar su cita. Continúa solo si tienes permiso para compartirlos.</p>
          <label className="field">Parentesco<select name="relationship" value={form.relationship} onChange={onChange}>{Object.entries(relationships).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field">Nombre del paciente<input required name="patientName" value={form.patientName} onChange={onChange} /></label>
          <label className="field">Fecha de nacimiento del paciente<input required type="date" name="patientBirthDate" value={form.patientBirthDate} onChange={onChange} /></label>
        </>
      )}
    </>
  );
}

export function CatalogOptions({ items, onSelect, disabled, slots = false, stacked = false }) {
  return (
    <div className={`mt-6 grid gap-3 ${stacked ? "" : "sm:grid-cols-3"}`}>
      {items.map((item) => (
        <button key={item.id} className="option-button" type="button" disabled={disabled} onClick={() => onSelect(item.id)}>
          {slots ? formatMexicoDateTime(item.starts_at) : item.name}
        </button>
      ))}
    </div>
  );
}
