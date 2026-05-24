import { useCallback, useMemo, useState } from 'react';
import { api } from '../api';
import type { RuntimeSettings } from '../types';

interface UseSettingsArgs {
  loadPipelineStatus: () => Promise<void>;
  loadLlmModels: () => Promise<void>;
  setError: (message: string | null) => void;
}

export function useSettings({ loadPipelineStatus, loadLlmModels, setError }: UseSettingsArgs) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<RuntimeSettings | null>(null);
  const [settingsApiKey, setSettingsApiKey] = useState('');
  const [settingsSaving, setSettingsSaving] = useState(false);

  const openSettings = useCallback(async () => {
    setSettingsOpen(true);
    setSettingsApiKey('');
    try {
      setSettingsDraft(await api.getRuntimeSettings());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setError]);

  const closeSettings = useCallback(() => {
    if (settingsSaving) return;
    setSettingsOpen(false);
    setSettingsDraft(null);
    setSettingsApiKey('');
  }, [settingsSaving]);

  const saveSettings = useCallback(async () => {
    if (!settingsDraft) return;
    setSettingsSaving(true);
    try {
      const saved = await api.updateRuntimeSettings({
        llm_endpoint: settingsDraft.llm_endpoint,
        llm_api_key: settingsApiKey,
        llm_model: settingsDraft.llm_model,
        llm_timeout_seconds: settingsDraft.llm_timeout_seconds,
        default_whisper_model: settingsDraft.default_whisper_model,
        asr_clip_seconds: settingsDraft.asr_clip_seconds,
      });
      setSettingsDraft(saved);
      setSettingsApiKey('');
      await loadPipelineStatus();
      await loadLlmModels();
      setSettingsOpen(false);
      setSettingsDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSettingsSaving(false);
    }
  }, [loadLlmModels, loadPipelineStatus, settingsApiKey, settingsDraft, setError]);

  return {
    settingsOpen,
    settingsDraft,
    settingsApiKey,
    settingsSaving,
    runtimeModelOptions: useMemo(() => settingsDraft?.llm_models || [], [settingsDraft]),
    openSettings,
    closeSettings,
    saveSettings,
    setSettingsDraft,
    setSettingsApiKey,
  };
}
