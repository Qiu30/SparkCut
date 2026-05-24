import { useCallback, useMemo, useState } from 'react';
import { api } from '../api';
import type { Template } from '../types';

export function useTemplates() {
  const [templates, setTemplates] = useState<Template[]>([]);

  const loadTemplates = useCallback(async () => {
    setTemplates(await api.listTemplates());
  }, []);

  return {
    templates,
    clipTemplates: useMemo(() => templates.filter((template) => template.type === 'clip'), [templates]),
    reviewTemplates: useMemo(() => templates.filter((template) => template.type === 'review'), [templates]),
    loadTemplates,
  };
}
