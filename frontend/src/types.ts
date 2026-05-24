export type JobStatus = 'queued' | 'running' | 'cancelled' | 'done' | 'error';

export type TemplateType = 'clip' | 'review';

export type FeedbackStatus = 'usable' | 'needs_edit' | 'rejected';

export interface WorkspaceSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  material_count: number;
  job_count: number;
  latest_job_status?: JobStatus | null;
}

export interface Material {
  id: string;
  workspace_id: string;
  filename: string;
  size_bytes: number;
  order_index: number;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  audio_status: string;
  probe_status: string;
  asr_status?: string | null;
  asr_updated_at?: string | null;
  asr_error_message?: string | null;
  created_at: string;
}

export interface JobConfig {
  contentType: string;
  durationRange: string;
  outputCount: number;
  pace: string;
  targetPlatform: string;
  aspectRatio: string;
  keepSuspense: boolean;
  clipRule: string;
  reviewRule: string;
  clipModel: string;
  reviewModel: string;
  whisperModel: string;
  dramaName: string;
  fontColor: string;
  cornerEnabled: boolean;
  endingEnabled: boolean;
}

export interface Template {
  id: string;
  name: string;
  type: TemplateType;
  config: Partial<JobConfig>;
  is_default: boolean;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobListItem {
  id: string;
  workspace_id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  rule_summary: string;
  whisper_model: string;
  output_count: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
}

export interface WorkspaceDetail {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  materials: Material[];
  jobs: JobListItem[];
}

export interface OutputVideo {
  id: string;
  job_id: string;
  name: string;
  filename: string;
  size_bytes: number;
  duration?: number | null;
  review_status: string;
  feedback_status?: FeedbackStatus | null;
  feedback_reason?: string | null;
  feedback_updated_at?: string | null;
  created_at: string;
}

export interface ExplainabilityTimelineItem {
  source: string;
  start: number;
  end: number;
  duration: number;
  score: number;
  reason: string;
  evidence_source?: string;
  evidence_text?: string;
}

export interface ExplainabilityExcludedItem {
  source: string;
  reason: string;
}

export interface ExplainabilityReviewItem {
  rule: string;
  time: string;
  result: string;
  action: string;
}

export interface ExplainabilityComparisonItem {
  name: string;
  duration_seconds: number;
  clip_count: number;
  strength: string;
  tradeoff: string;
}

export interface JobExplainability {
  summary?: {
    title: string;
    storyline: string;
    pacing: string;
    clip_count: number;
    estimated_duration: number;
    target_platform: string;
    aspect_ratio: string;
  };
  timeline?: ExplainabilityTimelineItem[];
  excluded?: ExplainabilityExcludedItem[];
  review_report?: {
    status: string;
    risk_level: string;
    model: string;
    items: ExplainabilityReviewItem[];
  };
  comparison?: ExplainabilityComparisonItem[];
}

export interface Job {
  id: string;
  workspace_id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  input_snapshot: Record<string, unknown>;
  explainability: JobExplainability;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  source_job_id?: string | null;
  outputs: OutputVideo[];
}

export interface LogsResponse {
  lines: string[];
  next_offset: number;
  status: JobStatus;
  stage: string;
  progress: number;
}

export interface StorageSummary {
  storage_bytes: number;
  material_count: number;
  output_count: number;
  missing_files: number;
  cleanup_available: boolean;
}

export interface PipelineStatus {
  mode: string;
  ffmpeg_available: boolean;
  ffprobe_available: boolean;
  llm_configured: boolean;
  llm_endpoint_configured: boolean;
  whisper_configured: boolean;
  max_concurrent_jobs: number;
  recover_jobs: boolean;
  queue_depth: number;
  active_jobs: number;
  worker_count: number;
  task_ready: boolean;
  blocking_requirements: string[];
  missing_env_vars: string[];
  warnings: string[];
}

export interface LlmModelsResponse {
  models: string[];
  default_model: string;
  source: string;
  error?: string | null;
}

export interface RuntimeSettings {
  pipeline_mode: string;
  llm_endpoint: string;
  llm_api_key_set: boolean;
  llm_api_key_preview: string;
  llm_model: string;
  llm_models: string[];
  llm_timeout_seconds: number;
  default_whisper_model: string;
  asr_clip_seconds: number;
}

export interface RuntimeSettingsUpdate {
  llm_endpoint?: string;
  llm_api_key?: string;
  llm_model?: string;
  llm_timeout_seconds?: number;
  default_whisper_model?: string;
  asr_clip_seconds?: number;
}
