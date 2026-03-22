from pathlib import Path

from .asr import transcribe_audio
from .summarizer import format_transcript_with_llm, group_transcript_segments, propose_title_from_summary, render_grouped_transcript_markdown, render_summary_markdown, summarize_text
from .utils import copy_file, ffmpeg_extract_audio, load_config, sha256_file


def process_video(file_path: str, raw_dir: Path, progress=None):
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Video not found: {file_path}")
    cfg = load_config(); audio_cfg = cfg.get("audio", {}); video_cfg = cfg.get("video", {}); processing_cfg = cfg.get("processing", {})
    raw_video_path = raw_dir / src.name; copy_file(src, raw_video_path)
    if progress: progress("extracting_audio", {"source": str(src.resolve()), "raw_path": str(raw_video_path)})
    extracted_audio_path = raw_dir / f"{src.stem}-audio.{video_cfg.get('extract_audio_codec', 'mp3')}"; ffmpeg_extract_audio(src, extracted_audio_path)
    if progress: progress("transcribing", {"audio_path": str(extracted_audio_path)})
    transcript = transcribe_audio(str(extracted_audio_path), model_size=audio_cfg.get("model_size", "small"), language=audio_cfg.get("language", "zh"), compute_type=audio_cfg.get("compute_type", "int8"), beam_size=audio_cfg.get("beam_size", 5), vad_filter=audio_cfg.get("vad_filter", True))
    content_text = transcript["full_text"]; language = transcript["meta"].get("language") or audio_cfg.get("language", "zh"); duration = transcript["meta"].get("duration")
    summary_data = summarize_text(content_text, content_type="video") if processing_cfg.get("summarize", True) else {"summary": "", "bullets": [], "action_items": [], "keywords": []}
    transcript_groups = group_transcript_segments(transcript["segments"], window_seconds=20.0)

    # 优先用 LLM 整理转录（繁转简 + 结构化），失败则降级到本地格式化
    llm_transcript_md = format_transcript_with_llm(content_text, transcript["segments"])
    if llm_transcript_md:
        transcript_md = llm_transcript_md
    else:
        transcript_md = render_grouped_transcript_markdown(transcript_groups, transcript["segments"], media_type="视频")

    content_md = "\n".join([render_summary_markdown(summary_data), "", transcript_md])
    summary = summary_data.get("summary", "") or (f"视频音轨时长约 {int(duration)} 秒" if duration else "")
    proposed_title = propose_title_from_summary(summary_data, content_text=content_text, media_type="视频")
    return {"type": "video", "source": str(src.resolve()), "source_type": "file", "title": proposed_title, "original_filename": src.stem, "language": language, "summary": summary, "content_md": content_md, "content_text": content_text, "status": "processed" if content_text.strip() else "partial", "raw_path": str(raw_video_path), "source_file_hash": sha256_file(src), "extracted_audio_path": str(extracted_audio_path), "summary_data": summary_data, "duration": duration}
