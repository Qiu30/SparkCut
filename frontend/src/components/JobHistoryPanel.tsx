import { fmtDate, statusClass, statusLabels } from '../appConfig';
import type { SparkCutController } from '../hooks/useSparkCutController';

export function JobHistoryPanel({ controller }: { controller: SparkCutController }) {
  const { workspace, selectedJob, selectJob } = controller;
  if (!workspace) return null;

  return (
          <section className="panel-section">
            <div className="section-title">任务历史</div>
            <div className="job-list">
              {workspace.jobs.length === 0 ? (
                <div className="inline-empty">暂无任务</div>
              ) : (
                workspace.jobs.map((job) => (
                  <button className={`job-row ${selectedJob?.id === job.id ? 'active' : ''}`} key={job.id} onClick={() => selectJob(job.id)}>
                    <span className={statusClass(job.status)}>{statusLabels[job.status]}</span>
                    <span className="job-rule">{job.rule_summary}</span>
                    <span className="job-meta">
                      {fmtDate(job.created_at)} · whisper: {job.whisper_model} · 输出 {job.output_count}
                      {job.duration_seconds ? ` · ${job.duration_seconds}s` : ''}
                    </span>
                  </button>
                ))
              )}
            </div>
          </section>
  );
}
