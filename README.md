# SparkCut

可控、可解释、可复用、可迭代的 AI 视频混剪工作台。

SparkCut 面向短剧、漫剧和剧情类短视频生产场景，用户上传多集素材后，由 AI 自动完成语音转写、剧情分析、片段筛选、合规审查和视频合成，输出带有剧名、字幕、角标包装的成片。整个过程透明可控——每个 AI 决策都有解释，每次配置都可复用，每个结果都可迭代。

## 核心功能

### 工作空间与素材管理

- 以工作空间为单位组织素材和任务，一部剧或一个项目一个空间
- 支持批量上传视频文件，自动探查时长、分辨率、音频状态
- 拖拽排序素材顺序，帮助 AI 按集数顺序理解剧情

### AI 混剪流水线

六阶段 Pipeline 自动运行：

1. **素材探查** — 读取素材列表和基础元数据
2. **ASR 转写** — Whisper 语音识别，生成字幕与对白线索，支持按文件指纹增量缓存
3. **剧情分析** — LLM 生成片段时间线、方案摘要和多方案对比
4. **审查过滤** — LLM 根据用户定义的合规规则标记风险片段
5. **视频合成** — ffmpeg 精确裁剪片段、拼接成片
6. **视频包装** — 叠加剧名、字幕颜色、角标和片尾配置

### AI 可解释性

每次任务完成后自动生成：

- **方案摘要** — 整体剪辑思路和目标
- **时间线草稿** — 每个选中片段的起止时间、来源素材和选择理由
- **排除片段** — 被排除的片段及排除原因
- **审查报告** — 合规风险命中条目、时间点和风险等级
- **方案对比** — 多个输出方案之间的差异说明

### 配置与模板

- 结构化参数控制成片时长、输出数量、内容类型、节奏风格、目标平台、画幅
- 自由文本输入补充特殊剧情、风格或限制要求
- 内置预置模板（高光、悬疑、情感、动作等），支持自定义模板保存、复制、设为默认
- 模型选择：可指定剪辑模型、审查模型和 Whisper 模型

### 任务管理

- 异步任务队列，支持并发上限控制
- 实时进度和阶段展示
- 增量日志流，可展开查看完整输入快照
- 任务取消、失败重试、复制配置创建新任务
- 服务重启后自动恢复未完成任务

### 结果迭代

- 输出视频在线播放和下载
- 对每个输出标记"可用 / 需修改 / 不可用"反馈
- 基于反馈的 AI 二次生成：支持"调整"（局部微调）和"重新生成"两种模式

## 产品优势

| 维度 | 说明 |
| --- | --- |
| **全链路 AI 闭环** | 从上传素材到输出成片，ASR → LLM 分析 → 合规审查 → ffmpeg 合成，一次提交自动完成 |
| **AI 决策透明** | 每个选中/排除片段都有理由，审查命中有时间点和原因，用户能判断结果是否可信 |
| **渐进式 Pipeline** | 支持三种运行模式：`real`（全真实）、`auto`（有能力用真实，缺了自动降级）、`mock`（纯演示） |
| **零外部依赖部署** | SQLite + 本地文件存储 + in-process 任务队列，单机 Docker Compose 一键启动，不需要 Redis/Postgres |
| **配置即资产** | 模板保存、任务复制、输入快照回溯，生产经验可沉淀可复用 |
| **LLM 广泛兼容** | 自动适配 OpenAI、DeepSeek、CodingPlan 等不同 LLM provider 的 API 路径格式 |
| **ASR 增量缓存** | 按文件指纹缓存转写结果，换素材不重转，同素材跨任务复用 |

## 技术栈

### 后端

- **Python 3.12** + **FastAPI** — 异步 Web 框架
- **SQLAlchemy 2.0** — ORM（SQLite 存储）
- **Pydantic v2** — 请求/响应 schema 校验
- **Whisper** (openai-whisper) — 语音转写
- **ffmpeg / ffprobe** — 视频裁剪、拼接、元数据探查
- **uv** — Python 包管理

### 前端

- **React 19** + **TypeScript** — UI 框架
- **Vite** — 构建工具与开发服务器
- **lucide-react** — 图标库

### 部署

- **Docker Compose** — 单机双容器部署（nginx + FastAPI）
- **nginx** — 前端 SPA 托管 + API 反向代理
- **GitHub Actions** — 多架构镜像构建（amd64 / arm64），推送至 GHCR

### 项目结构

```
SparkCut/
├── backend/
│   ├── app/
│   │   ├── pipeline/          # 六阶段处理流水线
│   │   │   ├── engine.py      # 状态机与阶段调度
│   │   │   ├── stages/        # 探查、ASR、分析、审查、合成、包装
│   │   │   ├── llm.py         # LLM HTTP 调用（可取消）
│   │   │   ├── explainability.py  # AI 方案归一化
│   │   │   └── ffmpeg.py      # ffmpeg 裁剪与拼接
│   │   ├── routers/           # FastAPI 路由（工作区、模板、任务、设置）
│   │   ├── models.py          # SQLAlchemy ORM（7 张表）
│   │   ├── schemas.py         # Pydantic API schema
│   │   ├── serialization.py   # ORM → dict 序列化
│   │   ├── worker.py          # in-process 线程池任务队列
│   │   ├── prompts.py         # LLM 提示词模板
│   │   ├── settings.py        # 环境变量配置
│   │   └── llm_models.py      # LLM URL 适配与模型列表
│   ├── scripts/               # Whisper 转写脚本
│   └── tests/                 # pytest 集成测试
├── frontend/
│   └── src/
│       ├── components/        # UI 组件（工作台、配置表单、进度、结果等）
│       ├── hooks/             # 自定义 React Hooks
│       ├── api.ts             # 类型安全的 API 客户端
│       └── types.ts           # TypeScript 类型定义
├── docker/                    # Dockerfile + nginx.conf
├── docs/                      # 部署指南、测试用例文档
└── PRD.md                     # 产品需求文档
```

## 部署

### Docker 部署（推荐）

```bash
# 1. 复制并编辑环境变量
cp .env.example .env
# 编辑 .env，至少替换 VIDEO_CUT_LLM_API_KEY 为你的 LLM API Key

# 2. 启动
docker compose up -d

# 3. 访问
# http://服务器IP:8080
```

默认端口 `8080`，可通过 `.env` 中的 `VIDEO_CUT_WEB_PORT` 修改。

详细的生产部署指南见 [docs/DEPLOYMENT_DOCKER.md](docs/DEPLOYMENT_DOCKER.md)，包含环境变量说明、挂载目录、备份策略和运维命令。

### 本地开发

**后端：**

```bash
cd backend
uv sync
cp .env.example .env   # 编辑 .env 配置 LLM key 等
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**前端：**

```bash
cd frontend
npm install
npm run dev
```

前端默认 http://127.0.0.1:5173，通过 Vite proxy 转发 `/api` 请求到后端 8000 端口。

## 测试

```bash
# 后端集成测试（12 个用例，覆盖完整任务闭环）
cd backend && uv run pytest

# 前端编译检查
cd frontend && npm run build
```

## 环境变量

核心配置项：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `VIDEO_CUT_PIPELINE_MODE` | Pipeline 模式：`real` / `auto` / `mock` | `auto` |
| `VIDEO_CUT_LLM_ENDPOINT` | OpenAI 兼容的 LLM API 地址 | — |
| `VIDEO_CUT_LLM_API_KEY` | LLM API Key | — |
| `VIDEO_CUT_LLM_MODEL` | 默认 LLM 模型 | `GLM-5.1` |
| `VIDEO_CUT_WHISPER_COMMAND` | Whisper 转写命令模板 | — |
| `VIDEO_CUT_MAX_CONCURRENT_JOBS` | 最大并发任务数 | `1` |
| `VIDEO_CUT_MAX_VIDEO_BYTES` | 单文件上传上限 | `2147483648`（2GB） |

完整环境变量列表见 [.env.example](.env.example)。

## 许可证

MIT
