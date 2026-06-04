"""
VOXScript - CLI 메인 파이프라인
사용법: python pipeline.py [소스] [옵션]

예시:
  python pipeline.py "https://drive.google.com/file/d/..."
  python pipeline.py "https://www.youtube.com/watch?v=..."
  python pipeline.py "./video.mp4" --lang es --format excel
  python pipeline.py "./video.mp4" --format all
"""

import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 로드 (API 키)
load_dotenv()

from DAO.downloader import download_audio
from DAO.transcriber import transcribe, SUPPORTED_LANGUAGES
from DAO.cleaner import clean
from DAO.translator import translate, TARGET_LANGUAGES
from DAO.formatter import format_and_save, OUTPUT_FORMATS


def print_banner():
    print("""
╔══════════════════════════════════════╗
║          VOXScript v0.1              ║
║   Audio → Transcribe → Translate     ║
╚══════════════════════════════════════╝
""")


def progress(step: str, pct: int):
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r[{bar}] {pct:3d}%  {step}", end="", flush=True)
    if pct >= 100:
        print()


def run(
    source: str,
    lang: str = "auto",
    target_lang: str = "KO",
    formats: list[str] = None,
    output_name: str = None,
    model: str = "medium",
    no_summary: bool = False,
    import_dir: str = None,
    export_dir: str = None,
    diarize: bool = False,
    num_speakers: int | None = None,
    speakers: list[str] = None,  # ["인터뷰어", "인터뷰이"] 등
):
    if formats is None:
        formats = ["txt_bilingual", "srt_bilingual"]

    # 출력 파일명 자동 생성
    if output_name is None:
        import re, time

        if os.path.exists(source):
            # 로컬 파일 → 파일명 그대로
            output_name = Path(source).stem
        else:
            # YouTube → 영상 ID (11자리 고유값)
            yt_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", source)
            if yt_match:
                output_name = yt_match.group(1)
            else:
                # Google Drive 폴더/파일 ID
                gdrive_match = re.search(
                    r"/(?:folders|file/d)/([a-zA-Z0-9_-]+)", source
                )
                if gdrive_match:
                    output_name = gdrive_match.group(1)
                else:
                    # 그 외 URL → 타임스탬프
                    output_name = f"output_{int(time.time())}"

    print_banner()
    print(f"  source    : {source}")
    print(f"  language  : {SUPPORTED_LANGUAGES.get(lang, lang)}")
    print(f"  translate : -> {TARGET_LANGUAGES.get(target_lang, target_lang)}")
    print(f"  formats   : {formats}")
    print(f"  name      : {output_name}")
    print(f"  import_dir: {import_dir or '~/Downloads/VOXScript/temp (default)'}")
    print(f"  export_dir: {export_dir or '~/Downloads/VOXScript/output (default)'}")
    print(f"  diarize   : {'ON' if diarize else 'OFF'}")
    print()

    try:
        import time as _time

        total_start = _time.time()

        def elapsed(start):
            return f"{_time.time() - start:.1f}s"

        # ── Step 1: 다운로드 ──────────────────────────────
        t = _time.time()
        progress("Downloading audio...", 5)
        audio_path = download_audio(
            source, output_name, import_dir=Path(import_dir) if import_dir else None
        )
        progress("Download complete", 20)
        print(f"\n  -> audio: {audio_path}  [{elapsed(t)}]")

        # ── Step 2: Whisper STT ───────────────────────────
        print()
        t = _time.time()
        transcribe_result = transcribe(
            str(audio_path),
            language=lang,
            model_size=model,
            progress_callback=progress,
        )
        progress("STT complete", 60)
        print(
            f"\n  -> segments: {len(transcribe_result.segments)} (raw)  [{elapsed(t)}]"
        )
        print(f"  -> language: {transcribe_result.detected_language}")

        # ── Step 3: Gemini 전처리 (중복 제거 + 문단 묶기) ──
        print()
        t = _time.time()
        cleaned_result = clean(
            transcribe_result,
            progress_callback=progress,
        )
        progress("Cleaning complete", 80)
        print(
            f"\n  -> cleaned: {cleaned_result.cleaned_count} "
            f"({cleaned_result.original_count - cleaned_result.cleaned_count} removed)  [{elapsed(t)}]"
        )

        # ── Step 4: DeepL 번역 ────────────────────────────
        print()
        t = _time.time()
        translation_result = translate(
            cleaned_result,
            target_lang=target_lang,
            progress_callback=progress,
        )
        progress("Translation complete", 93)
        print(
            f"\n  -> translated: {len(translation_result.segments)} segments  [{elapsed(t)}]"
        )
        print()

        # ── Step 4.5: Gemini 텍스트 기반 화자 구분 (선택) ──
        if diarize:
            t = _time.time()
            from DAO.diarizer import label_speakers

            speaker_map = label_speakers(
                translation_result.segments,
                speakers=speakers,
                progress_callback=progress,
            )
            if speaker_map:
                for seg in translation_result.segments:
                    label = speaker_map.get(seg.index, "")
                    if label:
                        seg.original = f"[{label}] {seg.original}"
                        seg.translated = f"[{label}] {seg.translated}"
                print(
                    f"  -> speaker labels applied: {len(speaker_map)} segments  [{elapsed(t)}]"
                )

        # ── Step 5: 포맷 & 저장 ───────────────────────────
        print()
        t = _time.time()
        format_result = format_and_save(
            translation_result,
            output_name=output_name,
            formats=formats,
            export_dir=Path(export_dir) if export_dir else None,
            use_claude_summary=not no_summary,
            progress_callback=progress,
        )
        progress("Done!", 100)

        # ── 결과 출력 ─────────────────────────────────────
        total_elapsed = _time.time() - total_start
        m, s = divmod(int(total_elapsed), 60)
        print(f"\n\n✅ 처리 완료! (총 소요시간: {m}분 {s}초)")
        print("저장된 파일:")
        for f in format_result.saved_files:
            print(f"  📄 {f}")

        if format_result.claude_summary:
            print("\n" + "─" * 40)
            print("📋 Gemini 요약:")
            print("─" * 40)
            print(format_result.claude_summary)

    except EnvironmentError as e:
        print(f"\n\n❌ 환경 설정 오류: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 오류 발생: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="VOXScript - 음원/영상 → 번역 스크립트 변환기"
    )
    parser.add_argument(
        "source", help="Google Drive URL / YouTube URL / 로컬 파일 경로"
    )
    parser.add_argument(
        "--lang",
        default="auto",
        choices=list(SUPPORTED_LANGUAGES.keys()),
        help=f"원본 언어 (기본: auto). 선택지: {', '.join(SUPPORTED_LANGUAGES.keys())}",
    )
    parser.add_argument(
        "--target",
        default="KO",
        choices=list(TARGET_LANGUAGES.keys()),
        help="번역 타겟 언어 (기본: KO 한국어)",
    )
    parser.add_argument(
        "--format",
        default="txt_bilingual,srt_bilingual",
        help=f"출력 포맷 (콤마 구분). 선택지: {', '.join(OUTPUT_FORMATS.keys())}",
    )
    parser.add_argument(
        "--name", default=None, help="출력 파일명 (기본: 소스명 자동 추출)"
    )
    parser.add_argument(
        "--model",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper 모델 크기 (기본: medium)",
    )
    parser.add_argument(
        "--import-dir",
        default=None,
        help="Temp folder for downloaded audio (default: ~/Downloads/VOXScript/temp)",
    )
    parser.add_argument(
        "--export-dir",
        default=None,
        help="Output folder for result files (default: ~/Downloads/VOXScript/output)",
    )
    parser.add_argument("--no-summary", action="store_true", help="Skip Gemini summary")
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Enable speaker diarization via Gemini text analysis",
    )
    parser.add_argument(
        "--speakers",
        nargs="+",
        default=None,
        metavar="NAME",
        help="Speaker names (e.g. --speakers 진행자 젠슨황 게스트)",
    )

    args = parser.parse_args()
    formats = [f.strip() for f in args.format.split(",")]

    run(
        source=args.source,
        lang=args.lang,
        target_lang=args.target,
        formats=formats,
        output_name=args.name,
        model=args.model,
        no_summary=args.no_summary,
        import_dir=args.import_dir,
        export_dir=args.export_dir,
        diarize=args.diarize,
        num_speakers=None,
        speakers=args.speakers,
    )


if __name__ == "__main__":
    main()
