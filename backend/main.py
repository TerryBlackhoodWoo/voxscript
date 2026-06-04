"""
VOXScript - FastAPI 서버
Electron에서 이 서버를 백그라운드로 띄우고 React UI와 통신
"""
# uvicorn main:app --host 127.0.0.1 --port 8765 --reload

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

sys.path.insert(0, str(Path(__file__).parent))

from DAO.downloader import download_audio
from DAO.transcriber import transcribe, SUPPORTED_LANGUAGES
from DAO.cleaner import clean
from DAO.translator import translate, TARGET_LANGUAGES
from DAO.formatter import format_and_save, OUTPUT_FORMATS

app = FastAPI(title="VOXScript API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict[str, dict] = {}


class ProcessRequest(BaseModel):
    source: str
    language: str = "auto"
    target_language: str = "KO"
    formats: list[str] = ["txt_bilingual", "srt_bilingual"]
    output_name: Optional[str] = None
    model_size: str = "medium"
    use_summary: bool = True
    import_dir: Optional[str] = None
    export_dir: Optional[str] = None
    diarize: bool = False           # ← 화자 구분
    speaker1: str = "인터뷰어"      # ← 화자1 이름
    speaker2: str = "인터뷰이"      # ← 화자2 이름


class JobStatus(BaseModel):
    job_id: str
    status: str
    step: str
    progress: int
    files: list[str] = []
    summary: Optional[str] = None
    error: Optional[str] = None


@app.get("/")
def root():
    return {"status": "ok", "service": "VOXScript API"}


@app.get("/languages")
def get_languages():
    return {"source": SUPPORTED_LANGUAGES, "target": TARGET_LANGUAGES}


@app.get("/formats")
def get_formats():
    return OUTPUT_FORMATS


@app.post("/process", response_model=JobStatus)
def start_process(req: ProcessRequest):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "step": "대기 중",
        "progress": 0,
        "files": [],
        "summary": None,
        "error": None,
    }

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


@app.get("/jobs")
def list_jobs():
    """완료된 작업 목록 반환 (사이드바용)"""
    return [
        {"job_id": jid, **{k: v for k, v in job.items()}}
        for jid, job in jobs.items()
        if job["status"] == "done"
    ]


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
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

        # Step 3: Gemini 전처리
        _update(job_id, "전처리 중... (Gemini)", 61)
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

        # Step 4.5: 화자 구분 (선택)
        if req.diarize:
            _update(job_id, "화자 구분 중... (Gemini)", 94)
            from DAO.diarizer import label_speakers
            speaker_map = label_speakers(
                translation_result.segments,
                speaker1=req.speaker1,
                speaker2=req.speaker2,
                progress_callback=progress,
            )
            if speaker_map:
                for seg in translation_result.segments:
                    label = speaker_map.get(seg.index, "")
                    if label:
                        seg.original = f"[{label}] {seg.original}"
                        seg.translated = f"[{label}] {seg.translated}"

        # Step 5: 저장
        _update(job_id, "Saving files...", 95)
        format_result = format_and_save(
            translation_result,
            output_name=output_name,
            formats=req.formats,
            export_dir=Path(req.export_dir) if req.export_dir else None,
            use_claude_summary=req.use_summary,
            progress_callback=progress,
        )

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