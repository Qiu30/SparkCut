import { useCallback, useMemo, useState } from 'react';
import { api } from '../api';
import { FALLBACK_LLM_MODEL, pipelineHint } from '../appConfig';
import type { PipelineStatus } from '../types';

export function usePipeline(
  normalizeConfigForModels: (models: string[], fallback: string, replaceBuiltInFallback?: boolean) => void,
) {
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [llmModels, setLlmModels] = useState<string[]>([FALLBACK_LLM_MODEL]);
  const [defaultLlmModel, setDefaultLlmModel] = useState(FALLBACK_LLM_MODEL);

  const loadPipelineStatus = useCallback(async () => {
    setPipelineStatus(await api.getPipelineStatus());
  }, []);

  const loadLlmModels = useCallback(async () => {
    try {
      const response = await api.getLlmModels();
      const models = response.models;
      const defaultModel = response.default_model || models[0] || FALLBACK_LLM_MODEL;
      setLlmModels(models);
      setDefaultLlmModel(defaultModel);
      normalizeConfigForModels(models, defaultModel, true);
    } catch {
      setLlmModels([]);
      setDefaultLlmModel(FALLBACK_LLM_MODEL);
      normalizeConfigForModels([], FALLBACK_LLM_MODEL);
    }
  }, [normalizeConfigForModels]);

  return {
    pipelineStatus,
    llmModels,
    defaultLlmModel,
    currentPipelineHint: pipelineHint(pipelineStatus),
    llmModelOptions: useMemo(() => llmModels, [llmModels]),
    loadPipelineStatus,
    loadLlmModels,
  };
}
