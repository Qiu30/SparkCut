import { ListRestart, Save } from 'lucide-react';
import type { SparkCutController } from '../hooks/useSparkCutController';
import { TemplateSelect } from './TemplateSelect';
import { ModelField } from './fields/ModelField';
import { NumberField } from './fields/NumberField';
import { SelectField } from './fields/SelectField';
import { TextArea } from './fields/TextArea';

export function JobConfigForm({ controller }: { controller: SparkCutController }) {
  const {
    workspace,
    config,
    clipTemplates,
    reviewTemplates,
    activeTemplateByType,
    dirtyTemplateByType,
    llmModelOptions,
    busy,
    updateConfig,
    applyTemplate,
    deleteTemplate,
    duplicateTemplate,
    setDefaultTemplate,
    saveTemplate,
    submitJob,
  } = controller;
  if (!workspace) return null;

  return (
          <section className="panel-section">
            <div className="section-title">混剪配置</div>
            <TemplateSelect
              title="剪辑模板"
              templates={clipTemplates}
              activeTemplateId={activeTemplateByType.clip}
              isActiveDirty={dirtyTemplateByType.clip}
              onApply={applyTemplate}
              onDelete={deleteTemplate}
              onDuplicate={duplicateTemplate}
              onDefault={setDefaultTemplate}
            />
            <div className="form-grid two">
              <SelectField label="内容类型" value={config.contentType} options={['高光', '悬疑', '搞笑', '情感', '动作', '剧情概要', '自定义']} onChange={(contentType) => updateConfig({ contentType }, 'clip')} />
              <SelectField label="成片时长" value={config.durationRange} options={['30 秒', '60 秒', '1-3 分钟', '3-5 分钟', '5-10 分钟', '自定义']} onChange={(durationRange) => updateConfig({ durationRange }, 'clip')} />
              <NumberField label="输出数量" value={config.outputCount} onChange={(outputCount) => updateConfig({ outputCount }, 'clip')} />
              <SelectField label="节奏风格" value={config.pace} options={['快节奏', '剧情向', '强反转', '情绪递进', '信息密集', '自定义']} onChange={(pace) => updateConfig({ pace }, 'clip')} />
              <SelectField label="目标平台" value={config.targetPlatform} options={['通用', '抖音', '快手', '视频号', '小红书', 'B站']} onChange={(targetPlatform) => updateConfig({ targetPlatform }, 'clip')} />
              <SelectField label="画幅" value={config.aspectRatio} options={['9:16', '16:9', '1:1', '保持原始']} onChange={(aspectRatio) => updateConfig({ aspectRatio }, 'clip')} />
            </div>
            <label className="check-row">
              <input type="checkbox" checked={config.keepSuspense} onChange={(event) => updateConfig({ keepSuspense: event.target.checked }, 'clip')} />
              保留悬念
            </label>
            <TextArea label="剪辑规则描述" value={config.clipRule} placeholder="如：选取高光时段，成片30秒，需要强反转开头" onChange={(clipRule) => updateConfig({ clipRule }, 'clip')} />
            <ModelField label="剪辑模型" value={config.clipModel} options={llmModelOptions} onChange={(clipModel) => updateConfig({ clipModel }, 'clip')} />
            <button className="secondary full" onClick={() => saveTemplate('clip')}>
              <Save size={15} /> 保存当前剪辑模板
            </button>

            <TemplateSelect
              title="审查模板"
              templates={reviewTemplates}
              activeTemplateId={activeTemplateByType.review}
              isActiveDirty={dirtyTemplateByType.review}
              onApply={applyTemplate}
              onDelete={deleteTemplate}
              onDuplicate={duplicateTemplate}
              onDefault={setDefaultTemplate}
            />
            <TextArea label="审查规则描述" value={config.reviewRule} placeholder="如：画面不能出现人民币、广告水印或二维码" onChange={(reviewRule) => updateConfig({ reviewRule }, 'review')} />
            <ModelField label="审查模型" value={config.reviewModel} options={llmModelOptions} onChange={(reviewModel) => updateConfig({ reviewModel }, 'review')} />
            <button className="secondary full" onClick={() => saveTemplate('review')}>
              <Save size={15} /> 保存当前审查模板
            </button>

            <div className="form-grid two">
              <SelectField label="Whisper 模型" value={config.whisperModel} options={['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']} onChange={(whisperModel) => updateConfig({ whisperModel }, 'clip')} />
              <label className="field">
                <span>字幕颜色</span>
                <input type="color" value={config.fontColor} onChange={(event) => updateConfig({ fontColor: event.target.value }, 'clip')} />
              </label>
            </div>
            <label className="field">
              <span>剧名</span>
              <input value={config.dramaName} placeholder="输入剧名" onChange={(event) => updateConfig({ dramaName: event.target.value }, 'clip')} />
            </label>
            <div className="toggle-row">
              <label><input type="checkbox" checked={config.cornerEnabled} onChange={(event) => updateConfig({ cornerEnabled: event.target.checked }, 'clip')} /> 角标</label>
              <label><input type="checkbox" checked={config.endingEnabled} onChange={(event) => updateConfig({ endingEnabled: event.target.checked }, 'clip')} /> 片尾</label>
            </div>
            <button className="primary full submit-button" onClick={submitJob} disabled={busy || workspace.materials.length === 0}>
              <ListRestart size={16} /> 开始混剪
            </button>
          </section>
  );
}
