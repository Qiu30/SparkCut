export function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type="number" min={1} max={5} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}
