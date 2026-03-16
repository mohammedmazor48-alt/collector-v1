from faster_whisper import WhisperModel

from .utils import format_timestamp

_model_cache = {}


def get_whisper_model(model_size: str = "small", compute_type: str = "int8"):
    key = (model_size, compute_type)
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(model_size, compute_type=compute_type)
    return _model_cache[key]


def transcribe_audio(audio_path: str, model_size: str = "small", language: str = "zh", compute_type: str = "int8", beam_size: int = 5, vad_filter: bool = True):
    model = get_whisper_model(model_size=model_size, compute_type=compute_type)
    segments, info = model.transcribe(audio_path, language=language, beam_size=beam_size, vad_filter=vad_filter)
    segment_list = []
    full_text_parts = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        item = {"start": float(seg.start), "end": float(seg.end), "start_ts": format_timestamp(seg.start), "end_ts": format_timestamp(seg.end), "text": text}
        segment_list.append(item)
        full_text_parts.append(text)
    return {"segments": segment_list, "full_text": "\n".join(full_text_parts), "meta": {"language": getattr(info, "language", language), "duration": getattr(info, "duration", None), "duration_after_vad": getattr(info, "duration_after_vad", None)}}
