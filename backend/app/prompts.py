"""LLM prompt templates and builder for the analysis stage."""

from __future__ import annotations

from typing import Any, Dict

SYSTEM_PROMPT = """\
你是一位资深短视频混剪导演和 AI 剪辑分析师。

## 你的职责

你同时承担两个角色：
1. **混剪导演** — 根据素材信息和用户配置，设计出结构完整、节奏合理的视频混剪方案。
2. **分析报告员** — 对方案的每一步决策给出可解释的理由，让用户理解"为什么选这些片段、为什么排除那些片段"。

## 你的工作方式

- 你收到的输入是素材元信息（文件名、时长、分辨率、音频状态）和用户配置（内容类型、目标时长、节奏风格等）。
- 你无法看到视频画面或听到音频，因此你的片段选择应基于素材的元信息特征和排序逻辑来推理。
- 你需要根据素材在列表中的顺序理解剧情走向（用户已按集数或时间排列）。

## 输出纪律

- 严格输出一个 JSON 对象，不要输出任何 markdown 格式（不要 ```json 标记）。
- 不要在 JSON 前后添加任何解释文字。
- 所有文本内容使用中文。
- 不要编造不确定的信息。如果你对某个片段的内容不确定，在 reason 中如实说明。"""

USER_PROMPT_TEMPLATE = """\
请为以下素材设计混剪方案。

## 素材清单（按用户排列顺序）

{materials_list}

## 混剪目标

- 内容类型：{content_type}
- 目标时长：{duration_range}
- 输出方案数：{output_count}
- 节奏风格：{pace}
- 目标平台：{target_platform}
- 目标画幅：{aspect_ratio}
- 保留悬念：{keep_suspense}
- 剪辑模型：{clip_model}
- 审查模型：{review_model}

## 剪辑规则

{clip_rule}

## 审查规则

{review_rule}

---

请输出 JSON，包含以下字段：

{{
  "summary": {{
    "title": "方案标题（如"悬疑高光精剪版"）",
    "storyline": "一段 2-3 句话的方案主线说明，描述本方案聚焦的剧情线或情绪线",
    "pacing": "节奏风格（与用户配置一致）",
    "clip_count": 入选片段数量,
    "estimated_duration": 预计总时长（秒）,
    "target_platform": "目标平台",
    "aspect_ratio": "画幅比例"
  }},
  "timeline": [
    {{
      "source": "素材文件名（必须与素材清单中的文件名完全一致）",
      "start": 起始秒数,
      "end": 结束秒数,
      "duration": 片段时长（秒）,
      "score": 片段评分（1.0-10.0，10 最高）,
      "reason": "选择该片段的理由（1-2 句话，具体说明为什么这个位置、这个时长）"
    }}
  ],
  "excluded": [
    {{
      "source": "素材文件名",
      "reason": "排除理由（具体说明为什么不适合本方案）"
    }}
  ],
  "review_report": {{
    "status": "passed 或 warning 或 blocked",
    "risk_level": "低 或 中 或 高",
    "model": "使用的审查模型名",
    "items": [
      {{
        "rule": "命中的审查规则名称",
        "time": "命中的时间点或时间段",
        "result": "审查结果说明",
        "action": "处理方式（允许输出 / 需人工复核 / 已剔除 / 阻断输出）"
      }}
    ]
  }},
  "comparison": [
    {{
      "name": "方案名称",
      "duration_seconds": 方案总时长（秒）,
      "clip_count": 片段数量,
      "strength": "本方案的主要优势",
      "tradeoff": "本方案的主要取舍或不足"
    }}
  ]
}}

{multi_plan_instruction}

## 关键约束

1. `timeline` 中的 `source` 必须与素材清单中的文件名完全匹配，不要修改或缩写。
2. 所有时间数值单位为秒，保留一位小数（如 12.5）。
3. 入选片段的 `start` 和 `duration` 之和不能超过该素材的总时长。
4. 入选片段的总 `duration` 应接近用户配置的目标时长。
5. `score` 取值范围 1.0 - 10.0，保留一位小数。
6. 如用户开启了 `keepSuspense`，方案结尾应保留悬念而非完整剧透。
7. 如有审查规则，`review_report` 中应逐一检查是否命中；如无审查规则，`status` 默认为 `passed`。
8. 如果素材有 ASR 文本，`timeline.reason` 必须优先引用字幕证据；如果素材没有 ASR，必须明确写“仅基于元信息推断”。
9. `timeline` 条目可以增加 `evidence_source` 字段，取值为 `asr`、`metadata` 或 `model_fallback`。"""

MULTI_PLAN_INSTRUCTION = """\
## 多方案输出要求（重要）

用户要求输出 {output_count} 个方案。除了上述的 `timeline`（作为第一个方案的片段列表）之外，
你**必须**额外输出一个 `timelines` 字段，包含所有方案的独立片段列表：

"timelines": [
  {{
    "name": "方案 1 名称（与 summary.title 一致）",
    "timeline": [
      {{ "source": "文件名", "start": ..., "end": ..., "duration": ..., "score": ..., "reason": "..." }}
    ]
  }},
  {{
    "name": "方案 2 名称",
    "timeline": [
      {{ "source": "文件名", "start": ..., "end": ..., "duration": ..., "score": ..., "reason": "..." }}
    ]
  }}
]

每个方案的 timeline 必须是独立的片段选择，有不同的剪辑思路或侧重点。
`timelines[0]` 应与顶层 `timeline` 内容一致。"""


def _format_audio_status(status: str) -> str:
    mapping = {"present": "有音频", "missing": "无音频"}
    return mapping.get(status, "音频状态未知")


def _asr_by_material(asr_bundle: Any) -> dict[str, Dict[str, Any]]:
    if not isinstance(asr_bundle, dict):
        return {}
    materials = asr_bundle.get("materials")
    if not isinstance(materials, list):
        return {}
    result: dict[str, Dict[str, Any]] = {}
    for item in materials:
        if isinstance(item, dict) and item.get("material_id"):
            result[str(item["material_id"])] = item
    return result


def _truncate_text(text: str, limit: int = 700) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[: limit // 2].rstrip()
    tail = text[-limit // 2 :].lstrip()
    return f"{head} ...（中间已截断）... {tail}"


def _format_asr_segments(segments: Any, limit: int = 8) -> str:
    if not isinstance(segments, list) or not segments:
        return "无分段字幕"
    selected = segments[: limit // 2]
    if len(segments) > limit:
        selected = [*selected, *segments[-(limit // 2) :]]
    lines = []
    for segment in selected:
        if not isinstance(segment, dict):
            continue
        start = segment.get("start")
        end = segment.get("end")
        text = str(segment.get("text") or "").strip()
        if text:
            lines.append(f"{start}s-{end}s：{text}")
    if len(segments) > limit:
        lines.insert(limit // 2, "（中间分段已截断）")
    return "\n".join(lines) if lines else "无分段字幕"


def _format_materials_list(materials: list[Dict[str, Any]], asr_bundle: Any = None) -> str:
    asr_items = _asr_by_material(asr_bundle)
    lines = []
    for index, material in enumerate(materials, start=1):
        if not isinstance(material, dict):
            continue
        filename = material.get("filename") or f"素材 {index}"
        duration = material.get("duration")
        duration_text = f"{float(duration):.1f}" if duration is not None else "时长未知"
        width = material.get("width")
        height = material.get("height")
        resolution = f"{width}x{height}" if width and height else "分辨率未知"
        audio = _format_audio_status(str(material.get("audio_status") or "unknown"))
        line = f"{index}. {filename} — 时长 {duration_text} 秒，分辨率 {resolution}，{audio}"
        asr = asr_items.get(str(material.get("id") or ""))
        if asr:
            status = asr.get("status") or "unknown"
            if status == "done":
                text = _truncate_text(str(asr.get("text") or ""))
                segments = _format_asr_segments(asr.get("segments"))
                line += f"\n   ASR 状态：done\n   ASR 文本：{text or '空'}\n   ASR 分段：\n{segments}"
            else:
                line += f"\n   ASR 状态：{status}，无可用字幕；该素材只能基于元信息推断。"
        else:
            line += "\n   ASR 状态：not_started，当前无字幕证据；该素材只能基于元信息推断。"
        lines.append(line)
    return "\n".join(lines) if lines else "（无素材信息）"


def build_llm_messages(snapshot: Dict[str, Any], model: str) -> list[Dict[str, str]]:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    materials = snapshot.get("materials", [])
    if not isinstance(materials, list):
        materials = []

    keep_suspense = config.get("keepSuspense")
    keep_suspense_text = "是" if keep_suspense else "否"
    clip_rule = str(config.get("clipRule") or "").strip()
    if not clip_rule:
        clip_rule = "无额外剪辑规则，由导演根据素材和目标自行判断。"
    review_rule = str(config.get("reviewRule") or "").strip()
    if not review_rule:
        review_rule = "无额外审查规则。"

    output_count = int(config.get("outputCount") or 1)
    multi_plan_instruction = ""
    if output_count > 1:
        multi_plan_instruction = MULTI_PLAN_INSTRUCTION.format(output_count=output_count)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        materials_list=_format_materials_list(materials, snapshot.get("asr_bundle")),
        content_type=config.get("contentType") or "高光",
        duration_range=config.get("durationRange") or "2-6 分钟",
        output_count=output_count,
        pace=config.get("pace") or "剧情向",
        target_platform=config.get("targetPlatform") or "通用",
        aspect_ratio=config.get("aspectRatio") or "9:16",
        keep_suspense=keep_suspense_text,
        clip_model=model,
        review_model=config.get("reviewModel") or model,
        clip_rule=clip_rule,
        review_rule=review_rule,
        multi_plan_instruction=multi_plan_instruction,
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_config_block(config: Dict[str, Any], clip_model: str) -> str:
    keep_suspense = "是" if config.get("keepSuspense") else "否"
    rows = [
        ("内容类型", config.get("contentType") or "高光"),
        ("目标时长", config.get("durationRange") or "30 秒"),
        ("输出方案数", config.get("outputCount") or 1),
        ("节奏风格", config.get("pace") or "剧情向"),
        ("目标平台", config.get("targetPlatform") or "通用"),
        ("目标画幅", config.get("aspectRatio") or "9:16"),
        ("保留悬念", keep_suspense),
        ("剪辑模型", clip_model),
        ("审查模型", config.get("reviewModel") or clip_model),
        ("Whisper 模型", config.get("whisperModel") or "base"),
        ("剧名", config.get("dramaName") or "无"),
        ("字幕颜色", config.get("fontColor") or "#ffff00"),
        ("角标", "开启" if config.get("cornerEnabled") else "关闭"),
        ("片尾", "开启" if config.get("endingEnabled") else "关闭"),
        ("剪辑规则", config.get("clipRule") or "无"),
        ("审查规则", config.get("reviewRule") or "无"),
    ]
    return "\n".join(f"- {label}：{value}" for label, value in rows)


# ---------------------------------------------------------------------------
# Refine prompts — adjust (局部调整) vs regenerate (重新生成)
# ---------------------------------------------------------------------------

REFINE_ADJUST_SYSTEM = SYSTEM_PROMPT + """\

## 当前任务

你正在对一个已有的混剪方案做局部调整。保留原方案的片段选择思路和整体结构，
只针对用户反馈中指出的具体问题做调整，未提及的部分尽量不动。"""

REFINE_ADJUST_USER = """\
## 当前配置（必须沿用）

{config_block}

## 素材清单（按用户排列顺序）

{materials_list}

## 原始方案

{original_plan}

## 用户反馈（需要调整的部分）

{feedback}

---

请在原方案基础上，只修改用户反馈中指出的部分，输出调整后的完整 JSON 方案。
保持原有的 summary、timeline、excluded、review_report、comparison 字段结构。
对于没有变化的片段，保留原始的 source、start、end 等数值不变。
必须沿用“当前配置”里的目标时长、画幅、平台、节奏、悬念设置和包装设置，不要回退到系统默认配置。
不要固定输出 3 个片段；片段数量应服务于当前配置的目标时长，并尽量延续原方案的片段规模。
不要使用“演示精剪版”这类默认标题，除非原方案本身就是这个标题。"""

REFINE_REGENERATE_SYSTEM = SYSTEM_PROMPT + """\

## 当前任务

用户对已有混剪方案不满意，你需要重新设计一个全新的方案。
原方案仅供参考，你需要了解用户不满意的地方并避免重复这些问题。
不要保留原方案的结构和片段选择，换一个完全不同的剪辑思路。"""

REFINE_REGENERATE_USER = """\
## 当前配置（必须沿用）

{config_block}

## 素材清单（按用户排列顺序）

{materials_list}

## 原方案（仅供参考，了解问题所在）

{original_plan}

## 用户反馈（不满意的原因和期望方向）

{feedback}

---

请设计一个全新的混剪方案，确保不重复原方案的问题。
输出完整 JSON 方案，包含 summary、timeline、excluded、review_report、comparison 字段。
必须沿用“当前配置”里的目标时长、画幅、平台、节奏、悬念设置和包装设置，不要回退到系统默认配置。
不要固定输出 3 个片段；片段数量应服务于当前配置的目标时长。
不要使用“演示精剪版”这类默认标题，除非用户明确要求。"""


def build_refine_messages(
    action: str,
    snapshot: Dict[str, Any],
    feedback: str,
) -> list[Dict[str, str]]:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    materials = snapshot.get("materials", [])
    if not isinstance(materials, list):
        materials = []
    explainability = snapshot.get("explainability", {})
    if not isinstance(explainability, dict) or not explainability:
        refine_request = snapshot.get("refine_request", {})
        explainability = (
            refine_request.get("original_explainability", {})
            if isinstance(refine_request, dict)
            else {}
        )
    if not isinstance(explainability, dict):
        explainability = {}

    import json
    original_plan = json.dumps(explainability, ensure_ascii=False, indent=2)

    materials_list = _format_materials_list(materials, snapshot.get("asr_bundle"))
    config_block = _format_config_block(config, str(config.get("clipModel") or "GLM-5.1"))

    if action == "regenerate":
        system = REFINE_REGENERATE_SYSTEM
        user = REFINE_REGENERATE_USER.format(
            config_block=config_block,
            materials_list=materials_list,
            original_plan=original_plan,
            feedback=feedback,
        )
    else:
        system = REFINE_ADJUST_SYSTEM
        user = REFINE_ADJUST_USER.format(
            config_block=config_block,
            materials_list=materials_list,
            original_plan=original_plan,
            feedback=feedback,
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


REVIEW_SYSTEM_PROMPT = """\
你是一位短视频合规审查员。你只负责根据用户审查规则、素材元信息、ASR 文本和当前混剪方案输出审查报告。
严格输出 JSON 对象，不要输出 markdown，不要添加解释文字。"""


REVIEW_USER_PROMPT = """\
## 当前配置

{config_block}

## 素材清单

{materials_list}

## 当前混剪方案

{explainability}

---

请输出 JSON：
{{
  "review_report": {{
    "status": "passed 或 warning 或 blocked",
    "risk_level": "低 或 中 或 高",
    "model": "{review_model}",
    "items": [
      {{
        "rule": "命中的审查规则名称",
        "time": "命中的时间点或时间段",
        "result": "审查结果说明",
        "action": "允许输出 / 需人工复核 / 已剔除 / 阻断输出"
      }}
    ]
  }}
}}"""


def build_review_messages(snapshot: Dict[str, Any], explanation: Dict[str, Any]) -> list[Dict[str, str]]:
    config = snapshot.get("config", {})
    if not isinstance(config, dict):
        config = {}
    materials = snapshot.get("materials", [])
    if not isinstance(materials, list):
        materials = []
    review_model = str(config.get("reviewModel") or config.get("clipModel") or "GLM-5.1")

    import json

    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": REVIEW_USER_PROMPT.format(
                config_block=_format_config_block(config, str(config.get("clipModel") or review_model)),
                materials_list=_format_materials_list(materials, snapshot.get("asr_bundle")),
                explainability=json.dumps(explanation, ensure_ascii=False, indent=2),
                review_model=review_model,
            ),
        },
    ]
