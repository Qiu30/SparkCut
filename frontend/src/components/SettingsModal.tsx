import { Save, XCircle } from 'lucide-react';
import type { RuntimeSettings } from '../types';
import { ModelField } from './fields/ModelField';
import { SelectField } from './fields/SelectField';

interface SettingsModalProps {
  settingsOpen: boolean;
  settingsDraft: RuntimeSettings | null;
  settingsApiKey: string;
  settingsSaving: boolean;
  runtimeModelOptions: string[];
  closeSettings: () => void;
  saveSettings: () => void;
  setSettingsDraft: (value: RuntimeSettings) => void;
  setSettingsApiKey: (value: string) => void;
}

export function SettingsModal({
  settingsOpen,
  settingsDraft,
  settingsApiKey,
  settingsSaving,
  runtimeModelOptions,
  closeSettings,
  saveSettings,
  setSettingsDraft,
  setSettingsApiKey,
}: SettingsModalProps) {
  if (!settingsOpen) return null;

  return (
<div className="modal-backdrop" onClick={closeSettings}>
  <div className="modal-card settings-card" onClick={(event) => event.stopPropagation()}>
    <div className="modal-head">
      <h2>运行设置</h2>
      <button className="ghost icon-button" onClick={closeSettings} disabled={settingsSaving} title="关闭">
        <XCircle size={16} />
      </button>
    </div>
    {!settingsDraft ? (
      <div className="inline-empty">正在读取设置…</div>
    ) : (
      <>
        <div className="settings-stack">
          <section className="settings-section first">
            <div className="settings-section-title">基础运行</div>
            <div className="form-grid two compact">
              <SelectField
                label="默认 Whisper 模型"
                value={settingsDraft.default_whisper_model}
                options={['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']}
                onChange={(default_whisper_model) => setSettingsDraft({ ...settingsDraft, default_whisper_model })}
              />
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">LLM 服务</div>
            <ModelField
              label="默认 LLM 模型"
              value={settingsDraft.llm_model}
              options={runtimeModelOptions}
              onChange={(llm_model) => setSettingsDraft({ ...settingsDraft, llm_model })}
            />
            <label className="field">
              <span>接口地址</span>
              <input
                value={settingsDraft.llm_endpoint}
                placeholder="https://example.com 或 https://example.com/v1"
                onChange={(event) => setSettingsDraft({ ...settingsDraft, llm_endpoint: event.target.value })}
              />
              <small className="field-hint">默认自动补 /v1/chat/completions；以 / 结尾不补 /v1；以 # 结尾强制使用原地址。</small>
            </label>
            <label className="field">
              <span>API Key</span>
              <input
                type="password"
                value={settingsApiKey}
                placeholder={settingsDraft.llm_api_key_set ? `已设置 ${settingsDraft.llm_api_key_preview}，留空不修改` : '请输入 API Key'}
                onChange={(event) => setSettingsApiKey(event.target.value)}
              />
            </label>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">ASR 转写</div>
            <label className="field">
              <span>截取秒数</span>
              <input
                type="number"
                min={0}
                value={settingsDraft.asr_clip_seconds}
                onChange={(event) => setSettingsDraft({ ...settingsDraft, asr_clip_seconds: Number(event.target.value) })}
              />
              <small className="field-hint">填 0 表示转写完整视频。保存后新任务会立即使用新配置。</small>
            </label>
          </section>
        </div>
        <div className="modal-actions">
          <button className="secondary" onClick={closeSettings} disabled={settingsSaving}>取消</button>
          <button className="primary" onClick={() => void saveSettings()} disabled={settingsSaving}>
            <Save size={16} /> {settingsSaving ? '保存中…' : '保存设置'}
          </button>
        </div>
      </>
    )}
  </div>
</div>
  );
}
