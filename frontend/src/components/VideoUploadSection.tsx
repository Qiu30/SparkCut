import { FileVideo, Trash2, Upload } from 'lucide-react';
import type { DragEvent } from 'react';
import { asrStatusLabels, fmtSize } from '../appConfig';
import type { SparkCutController } from '../hooks/useSparkCutController';

export function VideoUploadSection({ controller }: { controller: SparkCutController }) {
  const { workspace, uploading, uploadFiles, dropUploadFiles, setDraggingMaterial, dropMaterial, deleteMaterial } = controller;
  if (!workspace) return null;

  return (
          <section className="panel-section">
            <div className="section-title">视频文件</div>
            <label className="upload-zone" onDragOver={(event) => event.preventDefault()} onDrop={dropUploadFiles}>
              <Upload size={22} />
              <span>{uploading ? '上传中...' : '拖拽或点击上传视频'}</span>
              <input type="file" multiple accept=".mp4,.mkv,.avi,.mov,.webm" onChange={uploadFiles} disabled={uploading} />
            </label>
            <div className="video-list">
              {workspace.materials.length === 0 ? (
                <div className="inline-empty">暂无素材</div>
              ) : (
                workspace.materials.map((material) => (
                  <div
                    className="video-row"
                    draggable
                    key={material.id}
                    onDragStart={() => setDraggingMaterial(material.id)}
                    onDragOver={(event: DragEvent) => event.preventDefault()}
                    onDrop={() => dropMaterial(material.id)}
                  >
                    <span className="drag-handle">☰</span>
                    <FileVideo size={16} />
                    <div className="video-main">
                      <span className="video-name">{material.filename}</span>
                      <span className="video-meta">
                        {fmtSize(material.size_bytes)}
                        {material.duration ? ` · ${material.duration.toFixed(1)}s` : ''}
                        {material.width && material.height ? ` · ${material.width}x${material.height}` : ''}
                      </span>
                      <span className={`asr-pill ${material.asr_status || 'not_started'}`} title={material.asr_error_message || undefined}>
                        {asrStatusLabels[material.asr_status || 'not_started'] || material.asr_status || 'ASR 未转写'}
                      </span>
                    </div>
                    <button className="danger icon-button" onClick={() => deleteMaterial(material)} title="删除">
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
  );
}
