# SparkCut Docker 生产部署指南

本文档面向单机生产部署，默认使用 `docker compose` 启动前端 nginx、后端 FastAPI、SQLite、本地文件存储和 ffmpeg。LLM 通过 `.env` 配置；本地 Whisper/PyTorch 体积较大，默认不打进镜像，可按需开启。

## 1. 服务器要求

- Docker Engine 24+。
- Docker Compose v2.24+。
- 建议至少 4 核 CPU、8 GB 内存、20 GB 可用磁盘。
- 默认镜像不内置 Whisper/PyTorch，以避免生产部署被大依赖下载阻塞；需要本地 Whisper 时可设置 `VIDEO_CUT_BUILD_WITH_WHISPER=true` 后重新构建。

## 2. 一键部署

在项目根目录执行：

```bash
cp .env.example .env
```

编辑 `.env`，至少替换：

```env
VIDEO_CUT_LLM_API_KEY=replace-with-your-key
```

启动：

```bash
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

如果要换端口，修改 `.env`：

```env
VIDEO_CUT_WEB_PORT=80
```

如果需要把本地 Whisper 打进后端镜像，先在 `.env` 增加：

```env
VIDEO_CUT_BUILD_WITH_WHISPER=true
```

然后重新构建：

```bash
docker compose build --no-cache backend
docker compose up -d
```

## 3. 环境变量放什么

这些配置应放在 `.env` 或服务器密钥管理系统，不要写进代码或镜像：

| 变量 | 说明 | 默认建议 |
| --- | --- | --- |
| `VIDEO_CUT_PIPELINE_MODE` | `auto`、`real`、`mock` | `auto` |
| `VIDEO_CUT_LLM_ENDPOINT` | OpenAI-compatible LLM URL；普通地址自动补 `/v1/chat/completions`，以 `/` 结尾不补 `/v1`，以 `#` 结尾强制使用原地址 | CodingPlan `/v1` 地址 |
| `VIDEO_CUT_LLM_API_KEY` | LLM API key | 必填，不能提交 |
| `VIDEO_CUT_LLM_MODEL` | 默认模型 | `GLM-5.1` |
| `VIDEO_CUT_WHISPER_COMMAND` | 容器内 Whisper 命令，必须支持 `{output_file}` | 已在 `.env.example` 提供 |
| `VIDEO_CUT_DEFAULT_WHISPER_MODEL` | 任务未显式选择时使用的 Whisper 模型 | `base` |
| `VIDEO_CUT_BUILD_WITH_WHISPER` | 是否在镜像构建阶段安装 Whisper/PyTorch | `false` |
| `VIDEO_CUT_ASR_CLIP_SECONDS` | 每个素材截取给 Whisper 的秒数；`0` 表示整条视频转写，也是 ASR 缓存 key 的一部分 | `0` |
| `VIDEO_CUT_ASR_LANGUAGE` | Whisper 转写语言 | `zh` |
| `VIDEO_CUT_ASR_TIMEOUT_SECONDS` | 单个素材 ASR 命令超时时间，整条视频转写建议放宽 | `1800` |
| `VIDEO_CUT_DB_URL` | SQLite 路径 | `sqlite:////app/data/videocut.db` |
| `VIDEO_CUT_STORAGE_DIR` | 上传和输出文件目录 | `/app/storage` |
| `VIDEO_CUT_MAX_CONCURRENT_JOBS` | 并发任务数 | `1` |
| `VIDEO_CUT_MAX_VIDEO_BYTES` | 单视频大小上限 | `2147483648` |

生产环境建议先使用 `auto`。确认 LLM、Whisper、ffmpeg 都正常后，再切到 `real`。

## 4. 挂载目录

`docker-compose.yml` 默认把这些目录挂到宿主机：

```text
deploy/data        -> /app/data          SQLite 数据库
deploy/storage     -> /app/storage       上传视频、输出视频、ASR 结果
deploy/model-cache -> /app/model-cache   Whisper 模型缓存
```

ASR 会按工作空间和文件指纹增量缓存，典型路径为：

```text
deploy/storage/workspaces/{workspaceId}/asr/{fingerprint}/whisper_{model}_{language}_{seconds_or_full}.json
deploy/storage/workspaces/{workspaceId}/outputs/{jobId}/asr_bundle.json
```

这些目录需要备份，尤其是：

```text
deploy/data/videocut.db
deploy/storage/
```

示例备份命令：

```bash
tar -czf videocut-backup-$(date +%Y%m%d).tgz deploy/data deploy/storage .env
```

## 5. 常用运维命令

查看状态：

```bash
docker compose ps
```

查看后端日志：

```bash
docker compose logs -f backend
```

查看前端日志：

```bash
docker compose logs -f frontend
```

重启：

```bash
docker compose restart
```

更新代码后重新打包：

```bash
docker compose up -d --build
```

停止服务：

```bash
docker compose down
```

## 6. 生产注意事项

- `.env` 已被 `.gitignore` 忽略，真实 API key 不要提交。
- nginx 已设置 `client_max_body_size 2048m`，与默认 2 GB 上传限制匹配。
- 本部署是单机 SQLite 方案，适合内部使用和轻量生产；多用户高并发后建议升级为 Postgres、对象存储和独立任务队列。
- 若开启 `VIDEO_CUT_BUILD_WITH_WHISPER=true`，首次 Whisper 任务会慢一些，因为需要下载模型到 `deploy/model-cache/`。
- `real` 模式缺少 LLM key、Whisper 或 ffmpeg 时会阻止任务；`auto` 模式会提示并降级。

## 7. 健康检查

后端健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

期望返回：

```json
{"ok":true}
```

也可以在页面里创建工作空间、上传 MP4、启动任务，确认输出视频可播放。
