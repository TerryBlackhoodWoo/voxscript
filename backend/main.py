"""
VOXScript - FastAPI 서버
Electron에서 이 서버를 백그라운드로 띄우고 React UI와 통신
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# 백엔드 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from DAO.downloader import download_audio
from DAO.transcriber import transcribe, SUPPORTED_LANGUAGES
from DAO.cleaner import clean
from DAO.translator import translate, TARGET_LANGUAGES
from DAO.formatter import format_and_save, OUTPUT_FORMATS

app = FastAPI(title="VOXScript API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron에서 접근 허용
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 작업 상태 저장 (메모리) ─────────────────────────────
jobs: dict[str, dict] = {}


# ── 요청 모델 ───────────────────────────────────────────
class ProcessRequest(BaseModel):
    source: str
    language: str = "auto"
    target_language: str = "KO"
    formats: list[str] = ["txt_bilingual", "srt_bilingual"]
    output_name: Optional[str] = None
    model_size: str = "medium"
    use_summary: bool = True
    import_dir: Optional[str] = None   # None = ~/Downloads/VOXScript/temp
    export_dir: Optional[str] = None   # None = ~/Downloads/VOXScript/output


class JobStatus(BaseModel):
    job_id: str
    status: str      # pending / running / done / error
    step: str
    progress: int    # 0~100
    files: list[str] = []
    summary: Optional[str] = None
    error: Optional[str] = None


# ── 엔드포인트 ─────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "VOXScript API"}


@app.get("/languages")
def get_languages():
    return {
        "source": SUPPORTED_LANGUAGES,
        "target": TARGET_LANGUAGES,
    }


@app.get("/formats")
def get_formats():
    return OUTPUT_FORMATS


@app.post("/process", response_model=JobStatus)
def start_process(req: ProcessRequest):
    """비동기 처리 시작 → job_id 반환"""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "step": "대기 중",
        "progress": 0,
        "files": [],
        "summary": None,
        "error": None,
    }

    # 백그라운드 태스크로 처리
    import threading
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, req),
        daemon=True,
    )
    thread.start()

    return JobStatus(job_id=job_id, **jobs[job_id])


@app.get("/status/{job_id}", response_model=JobStatus)
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(job_id=job_id, **jobs[job_id])


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    """처리된 파일 다운로드"""
    file_path = Path("./output") / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@app.delete("/job/{job_id}")
def delete_job(job_id: str):
    if job_id in jobs:
        del jobs[job_id]
    return {"deleted": job_id}


# ── 파이프라인 실행 (스레드) ────────────────────────────
def _update(job_id: str, step: str, progress: int, **kwargs):
    jobs[job_id].update({"step": step, "progress": progress, **kwargs})


def _run_pipeline(job_id: str, req: ProcessRequest):
    try:
        jobs[job_id]["status"] = "running"
        output_name = req.output_name or f"output_{job_id}"

        def progress(step, pct):
            _update(job_id, step, pct)

        # Step 1: 다운로드
        _update(job_id, "Downloading audio...", 5)
        audio_path = download_audio(
            req.source,
            output_name,
            import_dir=Path(req.import_dir) if req.import_dir else None,
        )
        _update(job_id, "Download complete", 20)

        # Step 2: STT
        _update(job_id, "음성 인식 중... (Whisper)", 25)
        transcribe_result = transcribe(
            str(audio_path),
            language=req.language,
            model_size=req.model_size,
            progress_callback=progress,
        )
        _update(job_id, "음성 인식 완료", 60)

        # Step 3: Claude 전처리
        _update(job_id, "전처리 중... (Claude - 중복 제거/문단 묶기)", 61)
        cleaned_result = clean(
            transcribe_result,
            progress_callback=progress,
        )
        _update(job_id, "전처리 완료", 80)

        # Step 4: 번역
        _update(job_id, "번역 중... (DeepL)", 81)
        translation_result = translate(
            cleaned_result,
            target_lang=req.target_language,
            progress_callback=progress,
        )
        _update(job_id, "번역 완료", 93)

        # Step 5: 저장
        _update(job_id, "Saving files...", 94)
        format_result = format_and_save(
            translation_result,
            output_name=output_name,
            formats=req.formats,
            export_dir=Path(req.export_dir) if req.export_dir else None,
            use_claude_summary=req.use_summary,
            progress_callback=progress,
        )

        # 파일명만 추출 (경로 제거)
        filenames = [Path(f).name for f in format_result.saved_files]

        _update(
            job_id, "완료!", 100,
            status="done",
            files=filenames,
            summary=format_result.claude_summary,
        )

    except Exception as e:
        _update(job_id, f"오류: {e}", 0, status="error", error=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("VOXSCRIPT_PORT", 8765))
    print(f"[VOXScript] API 서버 시작: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
