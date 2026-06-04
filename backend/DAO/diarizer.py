"""
VOXScript - Gemini Text-based Speaker Diarization
Gemini 텍스트 분석으로 화자 구분 (pyannote 제거)
"""

import os
import json
from dataclasses import dataclass


def label_speakers(
    translated_segments,
    speakers: list[str] = None,  # None이면 Gemini가 자동 추론
    progress_callback=None,
) -> dict[int, str]:
    """
    번역된 세그먼트 텍스트를 Gemini로 분석해 화자 라벨 반환

    Returns:
        dict: {segment_index: "화자 라벨"}
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[Diarizer] GEMINI_API_KEY not found, skipping")
        return {}

    try:
        import google.genai as genai

        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[Diarizer] Gemini init failed: {e}")
        return {}

    if progress_callback:
        progress_callback("Gemini speaker labeling...", 94)

    segments = translated_segments
    total = len(segments)

    # 내레이션/오프닝 건너뛰고 중간 구간 샘플링
    # 전체의 10~40% 구간에서 샘플 추출 (실제 대화 시작 부분)
    sample_start = max(0, total // 10)
    sample_end = min(total, total * 4 // 10)
    sample_segs = segments[sample_start:sample_end][:40]

    sample = "\n".join(
        f"[{seg.index}] {seg.translated.strip()[:100]}" for seg in sample_segs
    )

    # 1단계: 화자 역할 파악
    # 사용자 지정 화자명이 있으면 힌트로 제공
    speaker_hint = ""
    if speakers:
        names = ", ".join(f'"{s}"' for s in speakers)
        speaker_hint = f"\n화자 이름 힌트 (가능하면 이 이름들 사용): {names}"

    role_prompt = f"""다음은 인터뷰/대화 영상의 번역 스크립트 중간 구간입니다.
{speaker_hint}

{sample}

분석 규칙:
- 질문을 하거나 진행을 이끄는 사람 = 인터뷰어/진행자
- 질문에 답변하거나 자신의 경험/생각을 길게 말하는 사람 = 인터뷰이/게스트
- 짧은 반응("맞아요", "그렇군요", "감사합니다") = 주로 인터뷰어
- 긴 설명/이야기 = 주로 인터뷰이
- 내레이션(3인칭으로 특정인 소개) = 별도 나레이터로 처리
- 화자 수는 실제 대화 구조에 맞게 1명 이상으로 판단

위 패턴을 바탕으로 JSON으로만 반환:
{{"speaker_count": 2, "roles": {{"화자1": "인터뷰어", "화자2": "인터뷰이"}}, "pattern": "구분 근거 설명", "has_narration": false}}
JSON만 반환."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=role_prompt,
        )
        role_text = (
            response.text.strip().replace("```json", "").replace("```", "").strip()
        )
        role_info = json.loads(role_text)
        print(f"[Diarizer] Role analysis: {role_info}")
    except Exception as e:
        print(f"[Diarizer] Role detection failed: {e}")
        return {}

    roles = role_info.get("roles", {})
    has_narration = role_info.get("has_narration", False)
    pattern = role_info.get("pattern", "")
    speaker_count = role_info.get("speaker_count", 1)

    # 화자가 1명이면 라벨링 불필요 (UNKNOWN 방지)
    if speaker_count <= 1 and not speakers:
        print("[Diarizer] Single speaker detected, skipping labeling")
        return {}

    # 사용자 지정 화자명 우선 적용, 없으면 Gemini 추론 결과 사용
    if speakers:
        role_list = speakers
    else:
        role_list = list(roles.values())

    # 화자 1명이면 라벨링 불필요
    if len(role_list) < 2:
        print(f"[Diarizer] Only {len(role_list)} speaker(s), skipping labeling")
        return {}

    interviewer = role_list[0]
    interviewee = role_list[1]
    extra_speakers = role_list[2:] if len(role_list) > 2 else []

    # 2단계: 청크별 화자 라벨링
    chunk_size = 50  # 100 → 50 (파싱 안정성 향상)
    result: dict[int, str] = {}

    for chunk_start in range(0, total, chunk_size):
        chunk = segments[chunk_start : chunk_start + chunk_size]

        if progress_callback:
            pct = 94 + int((chunk_start / total) * 4)
            progress_callback(f"Labeling speakers... ({chunk_start}/{total})", pct)

        chunk_text = "\n".join(
            f"[{seg.index}] {seg.translated.strip()[:120]}" for seg in chunk
        )

        all_speakers = [interviewer, interviewee] + extra_speakers
        speakers_str = " 또는 ".join(f'"{s}"' for s in all_speakers)

        label_prompt = f"""화자 구분 기준:
- {interviewer}: 질문, 짧은 반응, 대화 진행
- {interviewee}: 긴 답변, 자신의 경험/의견 설명
{f'- {", ".join(extra_speakers)}: 추가 화자' if extra_speakers else ''}
{f'- 나레이터: 3인칭으로 인물/상황 소개' if has_narration else ''}
패턴: {pattern}

아래 각 세그먼트의 화자를 판단하세요.
반드시 모든 index에 대해 {speakers_str} 중 하나를 배정하세요.
확실하지 않으면 문맥상 가장 가능성 높은 화자로 배정 (UNKNOWN 사용 금지).

세그먼트:
{chunk_text}

JSON만 반환 (index는 문자열):
{{"0": "{interviewee}", "1": "{interviewer}", ...}}"""

        # 재시도 로직 (최대 2회)
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=label_prompt,
                )
                label_text = (
                    response.text.strip()
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                chunk_labels = json.loads(label_text)
                for idx_str, label in chunk_labels.items():
                    result[int(idx_str)] = label
                break  # 성공시 재시도 중단
            except Exception as e:
                if attempt == 0:
                    print(f"[Diarizer] Chunk {chunk_start} failed, retrying... ({e})")
                else:
                    print(f"[Diarizer] Chunk {chunk_start} failed after retry: {e}")
                    # 실패한 청크는 인터뷰이로 기본값
                    for seg in chunk:
                        result[seg.index] = interviewee

    labeled = sum(1 for v in result.values() if v != "")
    print(f"[Diarizer] Labeled {labeled}/{total} segments")
    print(
        f"[Diarizer] {interviewer}: {sum(1 for v in result.values() if v == interviewer)} / "
        f"{interviewee}: {sum(1 for v in result.values() if v == interviewee)}"
    )
    return result
