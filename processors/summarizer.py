import json
import re
from collections import Counter

from openai import OpenAI

from .utils import first_non_empty, get_env, load_config

STOPWORDS_ZH = {"的", "了", "和", "是", "就", "都", "而", "及", "与", "着", "或", "一个", "我们", "你们", "他们", "这个", "那个", "然后", "可以", "需要", "进行", "如果", "因为", "所以", "就是", "没有", "这里", "已经", "一下", "一些", "这种", "还是", "以及", "主要"}
ACTION_HINTS = ["需要", "下一步", "待办", "TODO", "todo", "跟进", "安排", "确认", "处理", "修复", "补充", "实现", "推进", "完成", "准备", "整理"]

# 口语清洗词表
SPOKEN_FILLERS = ["啊", "呀", "嗯", "哦", "诶", "唉", "哎呀", "你知道", "我跟你说", "我告诉你", "怎么说呢", "就是说"]

# 常见纠错词表
COMMON_CORRECTIONS = {
    "房地产": ["房地产", "房地产"],
    "楼市": ["楼市", "楼是"],
    "供需": ["供需", "供需"],
    "道教": ["道教", "道叫"],
    "内丹": ["内丹", "内单"],
    "元神": ["元神", "原神"],
    "元气": ["元气", "原气"],
}

TITLE_STOPWORDS = {"我们", "你们", "他们", "这个", "那个", "因为", "所以", "如果", "就是", "然后", "可以", "需要", "主要", "问题", "内容", "视频", "音频"}


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"[。！？\n]+", text) if p.strip()]


def clean_spoken_text(text: str) -> str:
    """清理口语填充词，让文本更书面化"""
    if not text:
        return text
    result = text
    # 清理常见口语填充词
    for filler in SPOKEN_FILLERS:
        result = result.replace(filler, "")
    # 清理多余的"就是"、"对吧"、"这个"、"那个"
    result = re.sub(r"就是+", "", result)
    result = re.sub(r"对吧+", "", result)
    result = re.sub(r"这个+", "这", result)
    result = re.sub(r"那个+", "那", result)
    # 清理多余空格
    result = re.sub(r"\s+", " ", result).strip()
    return result


def extract_keywords(text: str, topn: int = 8) -> list[str]:
    """提取关键词，确保输出短词而非长句"""
    # 提取 2-8 字的中文词或英文单词
    tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{2,15}", text)
    tokens = [t for t in tokens if t not in STOPWORDS_ZH and len(t) <= 8]
    # 过滤掉明显的口语片段
    tokens = [t for t in tokens if not any(filler in t for filler in ["就是", "对吧", "这个", "那个"])]
    counter = Counter(tokens)
    # 优先选择高频且较短的词
    keywords = []
    for word, count in counter.most_common(topn * 2):
        if len(word) <= 8 and len(keywords) < topn:
            keywords.append(word)
    return keywords[:topn]


def score_sentence(sentence: str, keywords: list[str]) -> int:
    score = sum(2 for kw in keywords if kw in sentence)
    if any(h in sentence for h in ACTION_HINTS):
        score += 2
    if 12 <= len(sentence) <= 80:
        score += 1
    return score


def truncate_text(text: str, max_chars: int) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def summarize_text_local(text: str) -> dict:
    cfg = load_config(); summary_cfg = cfg.get("summary", {})
    max_input_chars = summary_cfg.get("max_input_chars", 12000)
    max_summary_chars = summary_cfg.get("max_summary_chars", 400)
    max_bullets = summary_cfg.get("max_bullets", 5)
    extract_action_items = summary_cfg.get("extract_action_items", True)
    text = truncate_text(text or "", max_input_chars).strip()
    if not text:
        return {"summary": "", "bullets": [], "action_items": [], "keywords": [], "backend": "local"}

    sentences = split_sentences(text)
    if not sentences:
        return {"summary": text[:max_summary_chars], "bullets": [], "action_items": [], "keywords": [], "backend": "local"}

    # 提取关键词（已优化为短词）
    keywords = extract_keywords(text, topn=8)

    # 按得分排序句子
    ranked = sorted(sentences, key=lambda s: score_sentence(s, keywords), reverse=True)

    # 选取要点句：去重、清洗口语、过滤太短的句子
    seen = set()
    top_sentences = []
    for s in ranked:
        cleaned = clean_spoken_text(s)
        if len(cleaned) < 10:
            continue
        key = cleaned[:30]
        if key not in seen:
            seen.add(key)
            top_sentences.append(cleaned)
        if len(top_sentences) >= max_bullets:
            break

    # 摘要：取得分最高的前 3 句拼成一段（更像摘要而非原句罗列）
    summary_sentences = top_sentences[:3]
    raw_summary = "。".join(summary_sentences)
    if not raw_summary.endswith("。"):
        raw_summary += "。"
    summary = truncate_text(raw_summary, max_summary_chars)

    # 要点：保留清洗后的句子，控制在 20-50 字
    bullets = []
    for s in top_sentences[:max_bullets]:
        if 10 <= len(s) <= 80:
            bullets.append(s)

    action_items = [s for s in sentences if any(h in s for h in ACTION_HINTS)][:max_bullets] if extract_action_items else []
    return {"summary": summary, "bullets": bullets, "action_items": action_items, "keywords": keywords, "backend": "local"}


def build_prompt(text: str, content_type: str = "generic", prompt_style: str = "default") -> str:
    style_hint = ""
    if prompt_style == "meeting" or content_type in ("audio", "video"):
        style_hint = "如果内容像会议/讨论，请优先提炼结论、分歧、行动项。"
    elif prompt_style == "article" or content_type == "web":
        style_hint = "如果内容像文章，请优先概括主题、核心观点、重要事实。"
    elif prompt_style == "ocr" or content_type in ("image", "pdf"):
        style_hint = "如果内容来自 OCR/PDF，请优先提炼关键信息、字段、结论，并忽略明显识别噪声。"
    return f"""你是一个内容摘要助手。请根据给定文本，输出结构化 JSON 摘要。
要求：
1. 输出必须是合法 JSON，不要带 markdown 代码块
2. JSON 结构必须是：
{{
  \"summary\": \"一段简洁中文摘要\",
  \"bullets\": [\"要点1\", \"要点2\"],
  \"action_items\": [\"行动项1\", \"行动项2\"],
  \"keywords\": [\"关键词1\", \"关键词2\"]
}}
3. summary 尽量控制在 120~220 字
4. bullets 最多 5 条
5. action_items 如果没有可以输出空数组
6. keywords 输出 3~8 个
7. {style_hint}

待处理文本如下：

{text}
""".strip()


def summarize_text_openai(text: str, content_type: str = "generic") -> dict:
    cfg = load_config(); summary_cfg = cfg.get("summary", {}); openai_cfg = summary_cfg.get("openai", {})
    text = truncate_text(text or "", summary_cfg.get("max_input_chars", 12000)).strip()
    api_key = first_non_empty(get_env("OPENAI_API_KEY"), openai_cfg.get("api_key"))
    base_url = first_non_empty(get_env("OPENAI_BASE_URL"), openai_cfg.get("base_url"), "https://api.openai.com/v1")
    model = first_non_empty(get_env("OPENAI_MODEL"), openai_cfg.get("model"), "gpt-4o-mini")
    if not api_key:
        raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY or summary.openai.api_key in config.yaml")
    default_headers = {}
    if "kimi.com" in (base_url or ""):
        default_headers["User-Agent"] = "claude-code/1.0"
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=openai_cfg.get("timeout_sec", 60), default_headers=default_headers)
    prompt = build_prompt(text=text, content_type=content_type, prompt_style=summary_cfg.get("prompt_style", "default"))
    resp = client.chat.completions.create(model=model, temperature=openai_cfg.get("temperature", 0.2), response_format={"type": "json_object"}, messages=[{"role": "system", "content": "你是一个严谨的中文摘要助手，只输出合法 JSON。"}, {"role": "user", "content": prompt}])
    data = json.loads(resp.choices[0].message.content.strip())
    return {"summary": data.get("summary", ""), "bullets": data.get("bullets", []) or [], "action_items": data.get("action_items", []) or [], "keywords": data.get("keywords", []) or [], "backend": "openai", "model": model, "base_url": base_url, "auth_source": "env" if get_env("OPENAI_API_KEY") else "config"}


def summarize_text(text: str, content_type: str = "generic") -> dict:
    cfg = load_config(); summary_cfg = cfg.get("summary", {})
    mode = summary_cfg.get("mode", "local"); fallback_to_local = summary_cfg.get("fallback_to_local", True)
    if not summary_cfg.get("enabled", True):
        return {"summary": "", "bullets": [], "action_items": [], "keywords": [], "backend": "disabled"}
    if mode == "local":
        return summarize_text_local(text)
    if mode == "openai":
        try:
            return summarize_text_openai(text, content_type=content_type)
        except Exception as e:
            if fallback_to_local:
                result = summarize_text_local(text)
                result["fallback_reason"] = str(e)
                result["backend_requested"] = "openai"
                result["backend"] = "local"
                return result
            raise
    return summarize_text_local(text)


def _ts_to_seconds(ts: str) -> float:
    """将 HH:MM:SS 或 MM:SS 格式时间戳转为秒数"""
    parts = ts.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        else:
            return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def light_correct_transcript_text(text: str) -> str:
    """对整理版转写做轻量纠错（仅高置信度同音误识别修正）"""
    if not text:
        return text
    result = text
    for correct_form, variants in COMMON_CORRECTIONS.items():
        for wrong_form in variants[1:]:
            if wrong_form != correct_form:
                result = result.replace(wrong_form, correct_form)
    return result


def group_transcript_segments(segments: list, window_seconds: float = 20.0) -> list:
    """将逐句 segments 按时间窗口聚合为段落，返回 [{"start_ts", "end_ts", "text"}, ...]"""
    if not segments:
        return []
    groups = []
    current_texts = []
    current_start = segments[0].get("start_ts", "00:00:00")
    window_start_sec = _ts_to_seconds(current_start)
    last_ts = current_start

    for seg in segments:
        ts = seg.get("start_ts", "00:00:00")
        sec = _ts_to_seconds(ts)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if sec - window_start_sec >= window_seconds and current_texts:
            groups.append({"start_ts": current_start, "end_ts": last_ts, "text": "".join(current_texts)})
            current_texts = [text]
            current_start = ts
            window_start_sec = sec
        else:
            current_texts.append(text)
        last_ts = ts

    if current_texts:
        groups.append({"start_ts": current_start, "end_ts": last_ts, "text": "".join(current_texts)})
    return groups


def propose_title_from_summary(summary_data: dict, content_text: str = "", media_type: str = "内容") -> str:
    """根据摘要/要点/关键词自动拟定一个更像人写的标题。"""
    bullets = [clean_spoken_text(str(x)).strip("。；;，, ") for x in (summary_data.get("bullets") or []) if str(x).strip()]
    keywords = [str(x).strip() for x in (summary_data.get("keywords") or []) if str(x).strip()]
    summary = clean_spoken_text((summary_data.get("summary") or "").strip())

    candidates = []
    for bullet in bullets:
        text = re.sub(r"^[第\d一二三四五六七八九十]+[点、.：:]?", "", bullet).strip("。；;，, ")
        if 8 <= len(text) <= 28:
            candidates.append(text)
    for kw in keywords:
        if 2 <= len(kw) <= 8 and kw not in TITLE_STOPWORDS:
            candidates.append(kw)

    if candidates:
        title = candidates[0]
        if len(title) < 10 and len(candidates) >= 2:
            extra = next((x for x in candidates[1:] if x != title and x not in title), "")
            if extra:
                title = f"{title}：{extra}"
        title = re.sub(r"\s+", " ", title).strip("。；;，, ")
        return title[:32]

    if summary:
        first_sentence = split_sentences(summary)
        if first_sentence:
            return first_sentence[0][:32].strip("。；;，, ")
        return summary[:32].strip("。；;，, ")

    cleaned_text = clean_spoken_text(content_text or "")
    sentences = split_sentences(cleaned_text)
    for sentence in sentences:
        if 8 <= len(sentence) <= 32:
            return sentence.strip("。；;，, ")

    return f"{media_type}转写记录"


def format_transcript_with_llm(full_text: str, segments: list) -> str | None:
    """用 LLM 整理转录文本：繁转简、去口语词、添加结构标题。
    返回完整的 Markdown 字符串（含整理版 + 折叠原文），失败返回 None。"""
    cfg = load_config()
    summary_cfg = cfg.get("summary", {})
    if not summary_cfg.get("enabled", True) or summary_cfg.get("mode") != "openai":
        return None
    openai_cfg = summary_cfg.get("openai", {})
    api_key = first_non_empty(get_env("OPENAI_API_KEY"), openai_cfg.get("api_key"))
    if not api_key:
        return None

    text = truncate_text(full_text or "", 14000).strip()
    prompt = f"""你是一个视频内容整理助手。请将以下视频语音转录内容整理成结构化的中文文章。

整理要求：
1. 将所有繁体字转换为简体字
2. 纠正明显的语音识别错误（同音字、近音字）
3. 去除口语填充词（啊、嗯、就是、对吧、你知道等）
4. 按内容逻辑划分段落，添加 ### 级别小标题
5. 合并相关内容，形成完整流畅的段落
6. 严格保持原文意思，不添加原文没有的内容

直接输出 Markdown 正文，不要加代码块，格式如下：
## 视频语音转写（整理版）

[整理后的正文，带 ### 小标题]

原始转录文本：
{text}"""

    try:
        base_url = first_non_empty(get_env("OPENAI_BASE_URL"), openai_cfg.get("base_url"), "https://api.openai.com/v1")
        model = first_non_empty(get_env("OPENAI_MODEL"), openai_cfg.get("model"), "gpt-4o-mini")
        default_headers = {}
        if "kimi.com" in (base_url or ""):
            default_headers["User-Agent"] = "claude-code/1.0"
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, default_headers=default_headers)
        resp = client.chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": "你是一个严谨的中文内容整理助手，输出规范 Markdown。"},
                {"role": "user", "content": prompt},
            ],
        )
        formatted = (resp.choices[0].message.content or "").strip()
        if not formatted:
            return None

        # 拼接折叠的逐句原文
        raw_lines = []
        for seg in (segments or []):
            ts = seg.get("start_ts", "")
            t = (seg.get("text") or "").strip()
            if t:
                raw_lines.append(f"[{ts}] {t}")
        raw_block = ""
        if raw_lines:
            raw_block = (
                "\n\n---\n\n"
                "<details>\n"
                "<summary>📋 点击查看逐句原文（带时间戳）</summary>\n\n"
                "```\n"
                + "\n".join(raw_lines)
                + "\n```\n\n</details>"
            )

        return formatted + raw_block

    except Exception as e:
        print(f"[!] LLM 转录整理失败，降级到本地格式化: {e}")
        return None



def render_grouped_transcript_markdown(groups: list, segments: list, media_type: str = "视频") -> str:
    """渲染整理版（带轻量纠错）+ 逐句原始版 Markdown"""
    lines = []

    # 整理版（分段 + 轻量纠错）
    lines.append(f"## {media_type}语音转写（整理版）")
    lines.append("")
    if groups:
        for g in groups:
            start = g["start_ts"]
            end = g["end_ts"]
            corrected = light_correct_transcript_text(clean_spoken_text(g["text"]))
            lines.append(f"[{start}-{end}]")
            lines.append(corrected)
            lines.append("")
    else:
        lines.append("（暂无转写内容）")
        lines.append("")

    # 逐句原始版（保留 ASR 原文）
    lines.append(f"## {media_type}语音转写（逐句原始版）")
    lines.append("")
    if segments:
        for seg in segments:
            ts = seg.get("start_ts", "")
            text = (seg.get("text") or "").strip()
            if text:
                lines.append(f"[{ts}] {text}")
    else:
        lines.append("（暂无转写内容）")
    lines.append("")

    return "\n".join(lines).strip()


def render_summary_markdown(summary_data: dict) -> str:
    lines = ["## 摘要", "", summary_data.get("summary", "") or "（暂无摘要）", ""]
    bullets = summary_data.get("bullets", [])
    if bullets:
        lines += ["## 要点", ""] + [f"- {item}" for item in bullets] + [""]
    action_items = summary_data.get("action_items", [])
    if action_items:
        lines += ["## 行动项", ""] + [f"- {item}" for item in action_items] + [""]
    keywords = summary_data.get("keywords", [])
    if keywords:
        lines += ["## 关键词", "", ", ".join(keywords), ""]
    backend = summary_data.get("backend", "")
    if backend:
        lines += ["## 摘要元信息", "", f"- backend: {backend}"]
        if summary_data.get("model"):
            lines.append(f"- model: {summary_data.get('model')}")
        if summary_data.get("fallback_reason"):
            lines.append(f"- fallback_reason: {summary_data.get('fallback_reason')}")
        lines.append("")
    return "\n".join(lines).strip()
