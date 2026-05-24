import { Ban, CheckCircle2, Download, MessageSquare, Wrench } from 'lucide-react';
import { feedbackLabels, fmtSize } from '../appConfig';
import type { SparkCutController } from '../hooks/useSparkCutController';
import { ExplainabilityPanel } from './ExplainabilityPanel';

export function ResultsPanel({ controller }: { controller: SparkCutController }) {
  const {
    selectedJob,
    refineState,
    refineLoading,
    submitOutputFeedback,
    submitRefine,
    setRefineState,
  } = controller;

  return (
            <section className="results-panel">
              {selectedJob && <ExplainabilityPanel job={selectedJob} />}
              <div className="section-title">输出视频</div>
              {!selectedJob ? (
                <div className="inline-empty">暂无结果</div>
              ) : selectedJob.outputs.length === 0 ? (
                <div className="inline-empty">
                  {selectedJob.status === 'done'
                    ? '任务完成但无可预览视频'
                    : selectedJob.status === 'cancelled'
                      ? '任务已取消'
                      : '等待任务完成'}
                </div>
              ) : (
                <div className="result-grid">
                  {selectedJob.outputs.map((output) => (
                    <article className="result-card" key={output.id}>
                      <h3>{output.name}</h3>
                      <video controls src={`/api/jobs/${selectedJob.id}/outputs/${output.id}`} />
                      <div className="result-meta">
                        <span>{fmtSize(output.size_bytes)}</span>
                        <span className="status done">{output.review_status === 'passed' ? '审查通过' : output.review_status}</span>
                      </div>
                      <a className="download-link" href={`/api/jobs/${selectedJob.id}/outputs/${output.id}?download=true`}>
                        <Download size={15} /> 下载
                      </a>
                      <div className="feedback-box">
                        <span>
                          <MessageSquare size={14} />
                          {output.feedback_status
                            ? `反馈：${feedbackLabels[output.feedback_status]}`
                            : '结果反馈'}
                        </span>
                        {output.feedback_reason && <em>{output.feedback_reason}</em>}
                        <div className="feedback-actions">
                          <button className={output.feedback_status === 'usable' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'usable')}>
                            <CheckCircle2 size={14} /> 可用
                          </button>
                          <button className={output.feedback_status === 'needs_edit' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'needs_edit')}>
                            <Wrench size={14} /> 需修改
                          </button>
                          <button className={output.feedback_status === 'rejected' ? 'secondary active' : 'secondary'} onClick={() => submitOutputFeedback(output.id, 'rejected')}>
                            <Ban size={14} /> 不可用
                          </button>
                        </div>
                      </div>
                      {refineState?.outputId === output.id && (
                        <div className="refine-dialog">
                          <strong>{refineState.action === 'adjust' ? '调整方案' : '重新生成'}</strong>
                          <textarea
                            placeholder={refineState.action === 'adjust' ? '告诉 AI 哪里需要调整…' : '告诉 AI 你期望的方向…'}
                            value={refineState.feedback}
                            onChange={(e) => setRefineState({ ...refineState, feedback: e.target.value })}
                            rows={3}
                          />
                          <div className="refine-actions">
                            <button className="primary" onClick={submitRefine} disabled={!refineState.feedback.trim() || refineLoading}>
                              {refineLoading ? 'AI 优化中…' : refineState.action === 'adjust' ? '让 AI 调整' : '让 AI 重新生成'}
                            </button>
                            <button className="secondary" onClick={() => setRefineState(null)}>取消</button>
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
  );
}
