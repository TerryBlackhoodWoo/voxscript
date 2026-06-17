"""
VOXScript - Whisper STT 모듈
로컬 CUDA 또는 OpenAI Whisper API 선택 가능
"""

import os
from datetime import timedelta
from pathlib import Path
from dataclasses import dataclass

from DAO.bin_paths import get_ffmpeg, get_ffprobe

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
    use_api: bool = None,  # None = 자동 (OPENAI_API_KEY 있으면 API, 없으면 로컬)
) -> TranscribeResult:
    """
    음원 → 텍스트 변환

    Args:
        audio_path: MP3 파일 경로
        language: 언어 코드 ("auto" = 자동 감지)
        model_size: Whisper 모델 크기 (로컬 전용)
        progress_callback: 진행상태 콜백
        use_api: True=OpenAI API, False=로컬, None=자동

    Returns:
        TranscribeResult
    """
    # 자동 감지: OPENAI_API_KEY 있으면 API 사용
    if use_api is None:
        use_api = bool(os.environ.get("OPENAI_API_KEY"))

    if use_api:
        return _transcribe_api(audio_path, language, progress_callback)
    else:
        return _transcribe_local(audio_path, language, model_size, progress_callback)


def _transcribe_api(
    audio_path: str,
    language: str = "auto",
    progress_callback=None,
) -> TranscribeResult:
    """OpenAI Whisper API로 STT - 파일 크기 초과 시 자동 청크 분할"""
    from openai import OpenAI

    MAX_SIZE = 24 * 1024 * 1024  # 24MB
    file_size = Path(audio_path).stat().st_size

    if file_size > MAX_SIZE:
        print(
            f"[Whisper API] File too large ({file_size/1024/1024:.1f}MB), splitting into chunks..."
        )
        return _transcribe_api_chunked(audio_path, language, progress_callback)

    if progress_callback:
        progress_callback("Whisper API transcribing...", 25)

    print(f"[Whisper API] Starting: {audio_path} (lang: {language})")
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    with open(audio_path, "rb") as f:
        kwargs = {
            "model": "whisper-1",
            "file": f,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if language != "auto":
            kwargs["language"] = language

        try:
            response = client.audio.transcriptions.create(**kwargs)
        except Exception as e:
            if "413" in str(e) or "Maximum content size" in str(e):
                raise RuntimeError(
                    "파일 크기가 25MB를 초과합니다 (Whisper API 제한).\n"
                    "짧은 영상(25분 이하)을 사용해주세요."
                )
            raise

    if progress_callback:
        progress_callback("Processing segments...", 60)

    segments = []
    for i, seg in enumerate(response.segments):
        segments.append(Segment(index=i, start=seg.start, end=seg.end, text=seg.text))

    detected = getattr(response, "language", language)
    print(f"[Whisper API] Done: {len(segments)} segments, lang={detected}")

    return TranscribeResult(
        segments=segments, detected_language=detected, audio_path=audio_path
    )


def _transcribe_api_chunked(
    audio_path: str,
    language: str = "auto",
    progress_callback=None,
) -> TranscribeResult:
    """파일을 20분 단위로 청크 분할 후 각각 Whisper API 호출"""
    import subprocess
    import tempfile
    from openai import OpenAI

    CHUNK_MINUTES = 20  # 청크당 20분 (24MB 여유있게)
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    # ffprobe로 총 길이 파악
    probe = subprocess.run(
        [
            get_ffprobe(),
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    total_seconds = float(probe.stdout.strip())
    chunk_seconds = CHUNK_MINUTES * 60
    n_chunks = int(total_seconds / chunk_seconds) + 1

    print(
        f"[Whisper API] Total: {total_seconds/60:.1f}min → {n_chunks} chunks ({CHUNK_MINUTES}min each)"
    )

    all_segments = []
    segment_index = 0
    detected_language = language

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i in range(n_chunks):
            start_sec = i * chunk_seconds
            if start_sec >= total_seconds:
                break

            chunk_path = Path(tmp_dir) / f"chunk_{i:03d}.mp3"

            # ffmpeg으로 청크 추출
            subprocess.run(
                [
                    get_ffmpeg(),
                    "-i",
                    audio_path,
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(chunk_seconds),
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "64k",
                    str(chunk_path),
                    "-y",
                ],
                capture_output=True,
                check=True,
            )

            if progress_callback:
                pct = 25 + int((i / n_chunks) * 35)
                progress_callback(f"Whisper API chunk {i+1}/{n_chunks}...", pct)

            print(f"[Whisper API] Chunk {i+1}/{n_chunks} (offset: {start_sec:.0f}s)")

            with open(chunk_path, "rb") as f:
                kwargs = {
                    "model": "whisper-1",
                    "file": f,
                    "response_format": "verbose_json",
                    "timestamp_granularities": ["segment"],
                }
                if language != "auto":
                    kwargs["language"] = language

                response = client.audio.transcriptions.create(**kwargs)

            if i == 0:
                detected_language = getattr(response, "language", language)

            # 오프셋 적용해서 세그먼트 추가
            for seg in response.segments:
                all_segments.append(
                    Segment(
                        index=segment_index,
                        start=seg.start + start_sec,  # ← 오프셋
                        end=seg.end + start_sec,  # ← 오프셋
                        text=seg.text,
                    )
                )
                segment_index += 1

    print(
        f"[Whisper API] Chunked done: {len(all_segments)} segments, lang={detected_language}"
    )

    return TranscribeResult(
        segments=all_segments,
        detected_language=detected_language,
        audio_path=audio_path,
    )


def _transcribe_local(
    audio_path: str,
    language: str = "auto",
    model_size: str = "medium",
    progress_callback=None,
) -> TranscribeResult:
    """로컬 Whisper CUDA로 STT"""
    import whisper

    if progress_callback:
        progress_callback("Loading model...", 10)

    print(f"[Whisper Local] Loading: {model_size} (CUDA)")
    model = whisper.load_model(model_size, device="cuda")

    whisper_lang = None if language == "auto" else language

    if progress_callback:
        progress_callback("Transcribing...", 30)

    print(f"[Whisper Local] Starting: {audio_path} (lang: {language})")
    raw = model.transcribe(
        audio_path,
        language=whisper_lang,
        task="transcribe",
        verbose=False,
    )

    if progress_callback:
        progress_callback("Processing segments...", 70)

    segments = [
        Segment(index=i, start=seg["start"], end=seg["end"], text=seg["text"])
        for i, seg in enumerate(raw["segments"])
    ]

    detected = raw.get("language", language)
    print(f"[Whisper Local] Done: {len(segments)} segments, lang={detected}")

    return TranscribeResult(
        segments=segments,
        detected_language=detected,
        audio_path=audio_path,
    )


def _format_time_srt(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
