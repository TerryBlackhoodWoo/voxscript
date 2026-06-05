"""
VOXScript - 번역 모듈
DeepL API (Free tier: 월 500,000자 무료)
입력: CleanedResult (Gemini 전처리 완료된 세그먼트)
"""

import os
import time
import deepl
from dataclasses import dataclass
from DAO.cleaner import CleanedResult, CleanedSegment

TARGET_LANGUAGES = {
    "KO": "한국어",
    "EN-US": "영어 (미국)",
    "EN-GB": "영어 (영국)",
    "JA": "일본어",
    "ZH": "중국어 (간체)",
    "FR": "프랑스어",
    "DE": "독일어",
}


@dataclass
class TranslatedSegment:
    index: int
    start: float
    end: float
    original: str
    translated: str

    def start_srt(self) -> str:
        from DAO.transcriber import _format_time_srt

        return _format_time_srt(self.start)

    def end_srt(self) -> str:
        from DAO.transcriber import _format_time_srt

        return _format_time_srt(self.end)

    def time_range(self) -> str:
        return f"{self.start_srt()} → {self.end_srt()}"


@dataclass
class TranslationResult:
    segments: list[TranslatedSegment]
    source_language: str
    target_language: str

    def to_bilingual_srt(self) -> str:
        lines = []
        for seg in self.segments:
            lines.append(str(seg.index + 1))
            lines.append(f"{seg.start_srt()} --> {seg.end_srt()}")
            lines.append(seg.original.strip())
            lines.append(seg.translated.strip())
            lines.append("")
        return "\n".join(lines)

    def to_translated_only_srt(self) -> str:
        lines = []
        for seg in self.segments:
            lines.append(str(seg.index + 1))
            lines.append(f"{seg.start_srt()} --> {seg.end_srt()}")
            lines.append(seg.translated.strip())
            lines.append("")
        return "\n".join(lines)

    def to_plain_text(self) -> str:
        return "\n".join(seg.translated.strip() for seg in self.segments)

    def to_bilingual_text(self) -> str:
        lines = []
        for seg in self.segments:
            lines.append(f"[{seg.start_srt()}] {seg.original.strip()}")
            lines.append(f"[번역] {seg.translated.strip()}")
            lines.append("")
        return "\n".join(lines)


def translate(
    cleaned_result: CleanedResult,
    target_lang: str = "KO",
    batch_size: int = 50,
    progress_callback=None,
) -> TranslationResult:
    # 원본이 한국어고 타겟도 한국어면 번역 스킵
    src_lang = cleaned_result.detected_language or ""
    if target_lang == "KO" and src_lang.lower() in ("ko", "korean"):
        print(f"[DeepL] Korean source detected, skipping translation")
        if progress_callback:
            progress_callback("Korean → skipping translation", 93)
        segments = [
            TranslatedSegment(
                index=seg.index,
                start=seg.start,
                end=seg.end,
                original=seg.text,
                translated=seg.text,
            )
            for seg in cleaned_result.segments
        ]
        return TranslationResult(
            segments=segments,
            source_language=src_lang,
            target_language=target_lang,
        )

    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPL_API_KEY not set in .env")

    translator = deepl.Translator(api_key)
    segments = cleaned_result.segments
    total = len(segments)
    translated_segments = []

    print(f"[DeepL] Translating: {total} segments → {target_lang}")

    for batch_start in range(0, total, batch_size):
        batch = segments[batch_start : batch_start + batch_size]
        texts = [seg.text.strip() for seg in batch]

        if progress_callback:
            pct = 80 + int((batch_start / total) * 12)
            progress_callback(f"DeepL translating... ({batch_start}/{total})", pct)

        results = translator.translate_text(texts, target_lang=target_lang)

        for seg, result in zip(batch, results):
            translated_segments.append(
                TranslatedSegment(
                    index=seg.index,
                    start=seg.start,
                    end=seg.end,
                    original=seg.text,
                    translated=result.text,
                )
            )

        if batch_start + batch_size < total:
            time.sleep(0.3)

    print(f"[DeepL] Done: {src_lang} → {target_lang}")

    return TranslationResult(
        segments=translated_segments,
        source_language=src_lang,
        target_language=target_lang,
    )
