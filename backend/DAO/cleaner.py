"""
VOXScript - Gemini Cleaner
Whisper 원문 중복/겹침 제거 + 문단 묶기
병렬 처리로 속도 개선
"""

import os
import json
import concurrent.futures
from dataclasses import dataclass
from DAO.transcriber import TranscribeResult, _format_time_srt


@dataclass
class CleanedSegment:
    index: int
    start: float
    end: float
    text: str

    def start_srt(self) -> str:
        return _format_time_srt(self.start)

    def end_srt(self) -> str:
        return _format_time_srt(self.end)


@dataclass
class CleanedResult:
    segments: list[CleanedSegment]
    detected_language: str
    original_count: int
    cleaned_count: int


def clean(
    transcribe_result: TranscribeResult,
    progress_callback=None,
    chunk_size: int = 150,
    max_workers: int = 3,  # 병렬 처리 수
) -> CleanedResult:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not found in .env")

    import google.genai as genai

    client = genai.Client(api_key=api_key)

    segments = transcribe_result.segments
    total = len(segments)
    print(
        f"[Cleaner] Start: {total} segments (chunk_size={chunk_size}, workers={max_workers})"
    )

    if progress_callback:
        progress_callback("Gemini preprocessing...", 66)

    # 청크 분할
    chunks = []
    for chunk_start in range(0, total, chunk_size):
        chunk = segments[chunk_start : chunk_start + chunk_size]
        raw_segs = [
            {
                "i": seg.index,
                "s": round(seg.start, 2),
                "e": round(seg.end, 2),
                "t": seg.text.strip(),
            }
            for seg in chunk
        ]
        chunks.append((chunk_start, raw_segs))

    total_chunks = len(chunks)
    results_map: dict[int, list[dict]] = {}
    completed = [0]

    def process_chunk(args):
        chunk_start, raw_segs = args
        result = _call_gemini(client, raw_segs)
        completed[0] += 1
        if progress_callback:
            pct = 66 + int((completed[0] / total_chunks) * 14)
            progress_callback(
                f"Gemini preprocessing... ({completed[0]}/{total_chunks} chunks)", pct
            )
        return chunk_start, result

    # 병렬 처리
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
        for future in concurrent.futures.as_completed(futures):
            chunk_start, result = future.result()
            results_map[chunk_start] = result

    # 순서대로 재조립
    cleaned_segments: list[CleanedSegment] = []
    global_index = 0
    for chunk_start, _ in chunks:
        for item in results_map[chunk_start]:
            cleaned_segments.append(
                CleanedSegment(
                    index=global_index, start=item["s"], end=item["e"], text=item["t"]
                )
            )
            global_index += 1

    cleaned_count = len(cleaned_segments)
    print(
        f"[Cleaner] Done: {total} -> {cleaned_count} ({total - cleaned_count} removed)"
    )

    return CleanedResult(
        segments=cleaned_segments,
        detected_language=transcribe_result.detected_language,
        original_count=total,
        cleaned_count=cleaned_count,
    )


def _call_gemini(client, raw_segs: list[dict]) -> list[dict]:
    prompt = f"""Whisper STT segments with overlapping/duplicate text. Clean and return ONLY a JSON array.

Input:
{json.dumps(raw_segs, ensure_ascii=False)}

Rules:
1. Remove overlapping/duplicate text between consecutive segments
2. Join incomplete sentences ONLY if clearly from the same speaker continuing the same thought
3. NEVER merge segments that appear to be from different speakers (e.g. question followed by answer)
4. NEVER merge short responses ("네", "감사합니다", "맞아요") with other segments
5. Keep interview Q&A structure intact - questions and answers stay separate
6. s = first segment start, e = last segment end
7. Keep all content - do not skip or summarize

Return ONLY JSON array, no other text:
[{{"s": 0.0, "e": 5.2, "t": "cleaned text"}}, ...]"""

    # 재시도 로직
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            raw_text = (
                response.text.strip().replace("```json", "").replace("```", "").strip()
            )
            result = json.loads(raw_text)
            if isinstance(result, list):
                return result
        except Exception as e:
            if attempt == 0:
                print(f"[Cleaner] Parse failed, retrying... ({e})")
            else:
                print(f"[Cleaner] Parse failed after retry, keeping original: {e}")

    return [{"s": s["s"], "e": s["e"], "t": s["t"]} for s in raw_segs]
