"""
VOXScript - Whisper STT 모듈
기존 whisper_transcribe.py 확장 버전
RTX 3060 CUDA 최적화
"""

import whisper
from datetime import timedelta
from pathlib import Path
from dataclasses import dataclass


# 지원 언어 목록 (자주 쓰는 것만)
SUPPORTED_LANGUAGES = {
    "auto": "자동 감지",
    "es": "스페인어",
    "en": "영어",
    "ko": "한국어",
    "ja": "일본어",
    "zh": "중국어",
    "fr": "프랑스어",
    "de": "독일어",
    "pt": "포르투갈어",
}


@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str

    def start_srt(self) -> str:
        return _format_time_srt(self.start)

    def end_srt(self) -> str:
        return _format_time_srt(self.end)


@dataclass
class TranscribeResult:
    segments: list[Segment]
    detected_language: str
    audio_path: str

    def to_plain_text(self) -> str:
        return "\n".join(seg.text.strip() for seg in self.segments)

    def to_srt(self) -> str:
        lines = []
        for seg in self.segments:
            lines.append(str(seg.index + 1))
            lines.append(f"{seg.start_srt()} --> {seg.end_srt()}")
            lines.append(seg.text.strip())
            lines.append("")
        return "\n".join(lines)


def transcribe(
    audio_path: str,
    language: str = "auto",
    model_size: str = "medium",
    progress_callback=None,
) -> TranscribeResult:
    """
    음원 → 텍스트 변환

    Args:
        audio_path: MP3 파일 경로
        language: 언어 코드 ("auto" = 자동 감지)
        model_size: Whisper 모델 크기 (tiny/base/small/medium/large)
        progress_callback: 진행상태 콜백 fn(step: str, pct: int)

    Returns:
        TranscribeResult
    """
    if progress_callback:
        progress_callback("모델 로딩 중...", 10)

    print(f"[Whisper] 모델 로딩: {model_size} (CUDA)")
    model = whisper.load_model(model_size, device="cuda")

    whisper_lang = None if language == "auto" else language

    if progress_callback:
        progress_callback("음성 인식 중...", 30)

    print(f"[Whisper] 변환 시작: {audio_path} (언어: {language})")
    raw = model.transcribe(
        audio_path,
        language=whisper_lang,
        task="transcribe",
        verbose=False,
    )

    if progress_callback:
        progress_callback("세그먼트 처리 중...", 70)

    segments = [
        Segment(
            index=i,
            start=seg["start"],
            end=seg["end"],
            text=seg["text"],
        )
        for i, seg in enumerate(raw["segments"])
    ]

    detected = raw.get("language", language)
    print(f"[Whisper] 완료: {len(segments)}개 세그먼트 / 감지 언어: {detected}")

    return TranscribeResult(
        segments=segments,
        detected_language=detected,
        audio_path=audio_path,
    )


def save_srt(result: TranscribeResult, output_path: str | None = None) -> str:
    """SRT 파일 저장 후 경로 반환"""
    if output_path is None:
        base = Path(result.audio_path).stem
        output_path = f"./output/{base}_원문.srt"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.to_srt())

    print(f"[Whisper] SRT 저장: {output_path}")
    return output_path


def _format_time_srt(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
