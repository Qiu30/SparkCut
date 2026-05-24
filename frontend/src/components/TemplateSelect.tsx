import { Copy, Star, Trash2 } from 'lucide-react';
import type { MouseEvent } from 'react';
import type { Template } from '../types';

export function TemplateSelect({
  title,
  templates,
  activeTemplateId,
  isActiveDirty,
  onApply,
  onDelete,
  onDuplicate,
  onDefault,
}: {
  title: string;
  templates: Template[];
  activeTemplateId: string | null;
  isActiveDirty: boolean;
  onApply: (template: Template) => void;
  onDelete: (template: Template, event: MouseEvent) => void;
  onDuplicate: (template: Template, event: MouseEvent) => void;
  onDefault: (template: Template, event: MouseEvent) => void;
}) {
  const selectedTemplate = templates.find((template) => template.id === activeTemplateId) || null;
  const stateLabel = selectedTemplate ? (isActiveDirty ? '已修改' : '当前') : '未选择';
  return (
    <div className="template-block">
      <div className="template-select-head">
        <label className="field template-select-field">
          <span>{title}</span>
          <select
            value={activeTemplateId || ''}
            onChange={(event) => {
              const template = templates.find((item) => item.id === event.target.value);
              if (template) void onApply(template);
            }}
          >
            <option value="">选择模板</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}{template.is_default ? '（默认）' : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="template-action-row">
          <button className="secondary icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDuplicate(selectedTemplate, event)} title="复制模板">
            <Copy size={14} />
          </button>
          <button className="secondary icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDefault(selectedTemplate, event)} title="设为默认">
            <Star size={14} />
          </button>
          <button className="danger icon-button" disabled={!selectedTemplate} onClick={(event) => selectedTemplate && onDelete(selectedTemplate, event)} title="删除模板">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className={`template-state ${selectedTemplate?.is_default ? 'default' : ''} ${selectedTemplate ? 'active' : ''}`}>
        <span>{stateLabel}</span>
        {selectedTemplate?.is_default && <span>默认</span>}
        {selectedTemplate && <em>{selectedTemplate.name}</em>}
      </div>
    </div>
  );
}
