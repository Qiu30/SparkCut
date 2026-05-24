export function ModelField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const remoteOptions = Array.from(new Set(options.map((item) => item.trim()).filter(Boolean)));
  const selectValue = remoteOptions.includes(value) ? value : '__custom__';
  const isCustom = remoteOptions.length === 0 || selectValue === '__custom__';
  return (
    <label className="field model-field">
      <span>{label}</span>
      <div className={isCustom ? 'model-picker custom' : 'model-picker'}>
        <select
          value={remoteOptions.length > 0 ? selectValue : ''}
          onChange={(event) => {
            const next = event.target.value;
            onChange(next === '__custom__' ? '' : next);
          }}
          disabled={remoteOptions.length === 0}
        >
          {remoteOptions.length === 0 ? (
            <option value="">未获取到模型</option>
          ) : (
            <>
              <option value="__custom__">自定义模型...</option>
              {remoteOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </>
          )}
        </select>
        {isCustom && (
          <input value={value} placeholder="手动输入模型名" onChange={(event) => onChange(event.target.value)} />
        )}
      </div>
      <small className="field-hint">
        {remoteOptions.length > 0 ? (
          <>已获取 {remoteOptions.length} 个模型；选择自定义后可手动输入。</>
        ) : (
          <>当前接口未返回模型，可手动输入。</>
        )}
      </small>
    </label>
  );
}
