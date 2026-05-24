import { useCallback, useState } from 'react';
import { defaultConfig, normalizeConfigModels } from '../appConfig';
import type { JobConfig, TemplateType } from '../types';

export function useJobConfig() {
  const [config, setConfig] = useState<JobConfig>(defaultConfig);
  const [activeTemplateByType, setActiveTemplateByType] = useState<Record<TemplateType, string | null>>({ clip: null, review: null });
  const [dirtyTemplateByType, setDirtyTemplateByType] = useState<Record<TemplateType, boolean>>({ clip: false, review: false });

  const normalizeCurrentConfig = useCallback(
    (models: string[], fallback: string, replaceBuiltInFallback = false) => {
      setConfig((current) => normalizeConfigModels(current, models, fallback, replaceBuiltInFallback));
    },
    [],
  );

  const markTemplateDirty = useCallback(
    (type: TemplateType | TemplateType[]) => {
      const types = Array.isArray(type) ? type : [type];
      setDirtyTemplateByType((current) => {
        const next = { ...current };
        let changed = false;
        types.forEach((item) => {
          if (activeTemplateByType[item] && !next[item]) {
            next[item] = true;
            changed = true;
          }
        });
        return changed ? next : current;
      });
    },
    [activeTemplateByType],
  );

  const updateConfig = useCallback(
    (patch: Partial<JobConfig>, dirtyType?: TemplateType | TemplateType[]) => {
      setConfig((current) => ({ ...current, ...patch }));
      if (dirtyType) markTemplateDirty(dirtyType);
    },
    [markTemplateDirty],
  );

  return {
    config,
    activeTemplateByType,
    dirtyTemplateByType,
    normalizeCurrentConfig,
    updateConfig,
    setConfig,
    setActiveTemplateByType,
    setDirtyTemplateByType,
  };
}
