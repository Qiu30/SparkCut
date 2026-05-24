# SparkCut 智能视频混剪工作台

这是 PRD v2 的分迭代实现。当前采用 `FastAPI + React`，使用 SQLite 和本地 `storage/`。默认保持 mock pipeline 方便演示；如果配置了 ffmpeg、Whisper 命令和 OpenAI-compatible Chat Completions 接口，可以切到 `auto` 或 `real` 模式接入真实能力。

## Docker 生产部署

项目已提供 Docker Compose 单机部署方案，前端由 nginx 托管，后端容器内置 ffmpeg，并安装本地 Whisper base 运行依赖。

```bash
cp .env.example .env
docker compose up -d --build
```

默认访问地址是 `http://服务器IP:8080`。生产环境变量、挂载目录、备份和运维命令见 [Docker 部署指南](docs/DEPLOYMENT_DOCKER.md)。

## 运行后端

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 运行前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址默认是 `http://127.0.0.1:5173/`，通过 Vite proxy 调用 `http://127.0.0.1:8000/api`。

## 测试

```powershell
cd backend
uv run pytest
```

```powershell
cd frontend
npm run build
```

## v0.4 Pipeline 配置

默认值可以直接运行演示闭环：

```powershell
$env:VIDEO_CUT_PIPELINE_MODE="mock"
```

接入真实能力时使用环境变量，不要把 API key 写入代码或提交：

```powershell
$env:VIDEO_CUT_PIPELINE_MODE="auto" # mock | auto | real
$env:VIDEO_CUT_LLM_ENDPOINT="https://wishub-x6.ctyun.cn/coding/v1"
$env:VIDEO_CUT_LLM_API_KEY="<your-api-key>"
$env:VIDEO_CUT_LLM_MODEL="GLM-5.1"
$env:VIDEO_CUT_WHISPER_COMMAND='uv run python scripts/run_whisper_base.py "{input}" --job-id {job_id} --seconds 12'
$env:VIDEO_CUT_ASR_TIMEOUT_SECONDS="300"
$env:VIDEO_CUT_FFMPEG_TIMEOUT_SECONDS="600"
$env:VIDEO_CUT_MAX_CONCURRENT_JOBS="1"
```

`auto` 会在能力缺失时降级为 mock 输出；`real` 会在缺少 ffmpeg、LLM 或 ASR 配置时让任务失败并记录原因。`GET /api/pipeline/status` 可查看当前 pipeline 模式、ffmpeg/ffprobe、LLM、Whisper 和队列状态。

LLM 地址兼容 OpenAI-compatible 写法：普通 host/path 会自动补 `/v1/chat/completions`；以 `/` 结尾时不自动补 `/v1`；以 `#` 结尾时强制使用输入地址。

本地 Whisper 脚本会使用 base 模型转写源视频前 12 秒，并把结果写入 `storage/asr/<jobId>_whisper_base.json`。完整长视频转写可调大 `--seconds` 和 `VIDEO_CUT_ASR_TIMEOUT_SECONDS`。

## v0.1 范围

- 工作空间列表、新建、详情。
- 视频上传、删除、拖拽排序和浏览器 metadata 保存。
- 结构化混剪配置、审查配置、模型和包装配置。
- 内置模板、自定义模板、删除模板。
- 模拟异步任务、阶段进度、增量日志。
- 任务取消、失败重试、复制配置创建新任务。
- 任务 input snapshot。
- 任务完成后复制首个 MP4 作为演示输出，支持在线播放和下载。

## v0.2 增强

- 上传限制：默认单文件最大 2GB、单工作空间最多 100 个素材、单任务最多 100 个素材，可通过环境变量覆盖。
- 素材探查：如果本机存在 `ffprobe`，后端会补充提取时长、分辨率和音频状态；否则继续使用浏览器 metadata。
- 模板生产力：支持模板最近使用、复制模板、设为默认模板。
- 任务追溯：任务列表和详情展示耗时，日志区可展开输入快照。
- 输出命名：演示输出使用统一 `videocut_<jobId>_demo_cut.mp4` 命名。
- 存储概览：`GET /api/storage/summary` 返回素材、输出和占用空间统计。

## v0.3 AI 可解释

- 任务完成后生成方案摘要、时间线草稿、排除片段、审查报告和方案对比。
- 输出视频支持“可用 / 需修改 / 不可用”反馈，反馈保存在任务快照中并追加日志。

## v0.4 真实 Pipeline 基础

- 引入可插拔 pipeline：mock、auto、real 三种模式。
- 预留 OpenAI-compatible LLM 适配，可用 CodingPlan endpoint 生成可解释方案。
- 预留 Whisper 命令接入；未配置时按模式降级或失败。
- 检测 ffmpeg 后可进行真实 MP4 裁剪、转码和基础包装；未安装时 auto 模式降级为 mock 输出。
- in-process 队列支持并发上限、队列状态、启动恢复未完成任务。后续可以替换为 Redis + RQ/Celery。
