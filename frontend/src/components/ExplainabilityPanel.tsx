import { evidenceLabels, fmtSeconds, isRecord, numberValue, textValue } from '../appConfig';
import type { Job } from '../types';

export function ExplainabilityPanel({ job }: { job: Job }) {
  const explainability = (job.explainability || {}) as Record<string, unknown>;
  const rawSummary = explainability.summary;
  const rawTimeline = explainability.timeline;
  const rawExcluded = explainability.excluded;
  const rawReview = explainability.review_report;
  const rawComparison = explainability.comparison;
  const timeline = Array.isArray(rawTimeline)
    ? rawTimeline.filter(isRecord).map((item, index) => ({
        source: textValue(item.source, textValue(item.filename, textValue(item.material_id, `片段 ${index + 1}`))),
        start: numberValue(item.start, numberValue(item.start_time)),
        end: numberValue(item.end, numberValue(item.end_time, numberValue(item.start) + numberValue(item.duration))),
        score: numberValue(item.score, 8.5),
        reason: textValue(item.reason, textValue(item.selection_reason, textValue(item.text_overlay, '历史任务未提供选择理由'))),
        evidence_source: textValue(item.evidence_source, textValue(item.evidenceSource, 'metadata')),
        evidence_text: textValue(item.evidence_text, textValue(item.evidenceText, '')),
      }))
    : [];
  const summary = isRecord(rawSummary)
    ? {
        title: textValue(rawSummary.title, '历史 AI 方案'),
        clip_count: numberValue(rawSummary.clip_count, timeline.length),
        estimated_duration: numberValue(rawSummary.estimated_duration),
        target_platform: textValue(rawSummary.target_platform, '-'),
        aspect_ratio: textValue(rawSummary.aspect_ratio, '-'),
        storyline: textValue(rawSummary.storyline, ''),
      }
    : typeof rawSummary === 'string' && rawSummary.trim()
      ? {
          title: '历史 AI 方案',
          clip_count: timeline.length,
          estimated_duration: timeline.reduce((sum, item) => sum + Math.max(0, item.end - item.start), 0),
          target_platform: '-',
          aspect_ratio: '-',
          storyline: rawSummary,
        }
      : null;
  const excluded = Array.isArray(rawExcluded)
    ? rawExcluded.map((item, index) =>
        isRecord(item)
          ? {
              source: textValue(item.source, textValue(item.filename, `排除片段 ${index + 1}`)),
              reason: textValue(item.reason, textValue(item.detail, '历史任务未提供排除原因')),
            }
          : {
              source: `排除片段 ${index + 1}`,
              reason: String(item),
            },
      )
    : [];
  const review = isRecord(rawReview)
    ? {
        status: textValue(rawReview.status, 'not_checked'),
        risk_level: textValue(rawReview.risk_level, '-'),
        model: textValue(rawReview.model, textValue((explainability.llm_source as Record<string, unknown> | undefined)?.model, '-')),
        items: Array.isArray(rawReview.items)
          ? rawReview.items.filter(isRecord).map((item) => ({
              time: textValue(item.time, '全片'),
              rule: textValue(item.rule, '历史审查'),
              result: textValue(item.result, '-'),
              action: textValue(item.action, '-'),
            }))
          : Array.isArray(rawReview.issues)
            ? rawReview.issues.map((item) =>
                isRecord(item)
                  ? {
                      time: textValue(item.time, '全片'),
                      rule: textValue(item.rule, '历史审查'),
                      result: textValue(item.result, textValue(item.detail, '-')),
                      action: textValue(item.action, '人工复核'),
                    }
                  : {
                      time: '全片',
                      rule: '历史审查',
                      result: String(item),
                      action: '人工复核',
                    },
              )
            : textValue(rawReview.details)
              ? [
                  {
                    time: '全片',
                    rule: '历史审查',
                    result: textValue(rawReview.details),
                    action: rawReview.status === 'passed' ? '允许输出' : '人工复核',
                  },
                ]
              : [],
      }
    : null;
  const comparison = Array.isArray(rawComparison)
    ? rawComparison.filter(isRecord).map((item, index) => ({
        name: textValue(item.name, `方案 ${index + 1}`),
        duration_seconds: numberValue(item.duration_seconds, summary?.estimated_duration || 0),
        clip_count: numberValue(item.clip_count, timeline.length),
        strength: textValue(item.strength, textValue(item.summary, '-')),
        tradeoff: textValue(item.tradeoff, textValue(item.risk, '-')),
      }))
    : isRecord(rawComparison)
      ? [
          {
            name: '历史方案对比',
            duration_seconds: summary?.estimated_duration || 0,
            clip_count: timeline.length,
            strength: textValue(rawComparison.value_gain, textValue(rawComparison.new_structure, '-')),
            tradeoff: textValue(rawComparison.original_structure, '需结合人工复核判断'),
          },
        ]
      : [];

  return (
    <section className="explain-panel">
      <div className="section-title">AI 时间线草稿</div>
      {!summary ? (
        <div className="inline-empty">
          {job.status === 'done' ? '暂无可解释数据' : '任务完成后生成方案解释'}
        </div>
      ) : (
        <>
          <div className="summary-strip">
            <div>
              <span>方案</span>
              <strong>{summary.title}</strong>
            </div>
            <div>
              <span>片段</span>
              <strong>{summary.clip_count} 个</strong>
            </div>
            <div>
              <span>预计时长</span>
              <strong>{fmtSeconds(summary.estimated_duration)}</strong>
            </div>
            <div>
              <span>平台/画幅</span>
              <strong>{summary.target_platform} · {summary.aspect_ratio}</strong>
            </div>
          </div>
          <p className="storyline">{summary.storyline}</p>

          <details className="explain-detail" open>
            <summary>时间线草稿</summary>
            {timeline.length === 0 ? (
              <div className="inline-empty">暂无入选片段</div>
            ) : (
              <div className="timeline-list">
                {timeline.map((item, index) => (
                  <div className="timeline-item" key={`${item.source}-${index}`}>
                    <span className="timeline-index">{index + 1}</span>
                    <div>
                      <strong>{item.source}</strong>
                      <p>{fmtSeconds(item.start)} - {fmtSeconds(item.end)} · 评分 {item.score}</p>
                      <span className={`evidence-pill ${item.evidence_source || 'metadata'}`}>
                        {evidenceLabels[item.evidence_source || 'metadata'] || '元信息推断'}
                      </span>
                      <em>{item.reason}</em>
                      {item.evidence_source !== 'asr' && (
                        <small className="evidence-note">该片段尚未由字幕验证</small>
                      )}
                      {item.evidence_text && <small className="evidence-note">{item.evidence_text}</small>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </details>

          <div className="explain-grid">
            <details className="explain-detail">
              <summary>排除片段</summary>
              {excluded.length === 0 ? (
                <div className="inline-empty">没有被排除的素材</div>
              ) : (
                <ul>
                  {excluded.map((item, index) => (
                    <li key={`${item.source}-${index}`}>
                      <strong>{item.source}</strong>
                      <span>{item.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </details>

            <details className="explain-detail">
              <summary>审查报告</summary>
              {review ? (
                <>
                  <div className="review-head">
                    <span className={review.status === 'passed' ? 'status done' : 'status running'}>
                      {review.status === 'passed' ? '通过' : review.status}
                    </span>
                    <span>风险：{review.risk_level}</span>
                    <span>{review.model}</span>
                  </div>
                  <ul>
                    {review.items.map((item, index) => (
                      <li key={`${item.rule}-${index}`}>
                        <strong>{item.time} · {item.rule}</strong>
                        <span>{item.result}，{item.action}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <div className="inline-empty">暂无审查报告</div>
              )}
            </details>
          </div>

          {comparison.length > 0 && (
            <div className="comparison-row">
              {comparison.map((item) => (
                <article className="comparison-card" key={item.name}>
                  <strong>{item.name}</strong>
                  <span>{fmtSeconds(item.duration_seconds)} · {item.clip_count} 段</span>
                  <p>{item.strength}</p>
                  <em>{item.tradeoff}</em>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
