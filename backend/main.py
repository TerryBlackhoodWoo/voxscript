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
    diarize: bool = False
    speakers: list[str] = []  # ← speakers 리스트


class JobStatus(BaseModel):
    job_id: str
    status: str
    step: str
    progress: int
    files: list[str] = []
    summary: Optional[str] = None
    error: Optional[str] = None
    log: list[str] = []  # ← 로그 추가


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
        "step": "Waiting...",
        "progress": 0,
        "files": [],
        "summary": None,
        "error": None,
        "log": [],
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


def _log(job_id: str, msg: str):
    """로그 추가 (최대 50줄 유지)"""
    print(f"[VOXScript] {msg}")
    logs = jobs[job_id].get("log", [])
    logs.append(msg)
    if len(logs) > 50:
        logs = logs[-50:]
    jobs[job_id]["log"] = logs


def _run_pipeline(job_id: str, req: ProcessRequest):
    try:
        import time as _time

        total_start = _time.time()

        def elapsed():
            return f"{_time.time() - total_start:.1f}s"

        jobs[job_id]["status"] = "running"
        output_name = req.output_name or f"output_{job_id}"

        def progress(step, pct):
            _update(job_id, step, pct)

        # Step 1: 다운로드
        _update(job_id, "Downloading audio...", 5)
        _log(job_id, f"[1/5] Downloading: {req.source[:60]}...")
        t = _time.time()
        audio_path = download_audio(
            req.source,
            output_name,
            import_dir=Path(req.import_dir) if req.import_dir else None,
        )
        _update(job_id, "Download complete", 20)
        _log(
            job_id,
            f"[1/5] Download complete [{_time.time()-t:.1f}s] → {audio_path.name}",
        )

        # Step 2: STT
        _update(job_id, "Whisper STT...", 25)
        _log(
            job_id,
            f"[2/5] Whisper STT starting (lang: {req.language}, model: {req.model_size})",
        )
        t = _time.time()
        transcribe_result = transcribe(
            str(audio_path),
            language=req.language,
            model_size=req.model_size,
            progress_callback=progress,
        )
        _update(job_id, "STT complete", 60)
        _log(
            job_id,
            f"[2/5] STT complete [{_time.time()-t:.1f}s] → {len(transcribe_result.segments)} segments, lang={transcribe_result.detected_language}",
        )

        # Step 3: Gemini 전처리
        _update(job_id, "Gemini preprocessing...", 61)
        _log(
            job_id,
            f"[3/5] Gemini preprocessing ({len(transcribe_result.segments)} segments)...",
        )
        t = _time.time()
        cleaned_result = clean(
            transcribe_result,
            progress_callback=progress,
        )
        _update(job_id, "Preprocessing complete", 80)
        _log(
            job_id,
            f"[3/5] Preprocessing complete [{_time.time()-t:.1f}s] → {cleaned_result.cleaned_count} segments ({cleaned_result.original_count - cleaned_result.cleaned_count} removed)",
        )

        # Step 4: 번역
        _update(job_id, "DeepL translating...", 81)
        _log(
            job_id,
            f"[4/5] DeepL translating ({cleaned_result.cleaned_count} segments)...",
        )
        t = _time.time()
        translation_result = translate(
            cleaned_result,
            target_lang=req.target_language,
            progress_callback=progress,
        )
        _update(job_id, "Translation complete", 93)
        _log(job_id, f"[4/5] Translation complete [{_time.time()-t:.1f}s]")

        # Step 4.5: 화자 구분 (선택)
        if req.diarize:
            _update(job_id, "Speaker diarization...", 94)
            _log(
                job_id,
                f"[4.5] Speaker diarization (speakers: {req.speakers or 'auto'})...",
            )
            t = _time.time()
            from DAO.diarizer import label_speakers

            speaker_map = label_speakers(
                translation_result.segments,
                speakers=req.speakers if req.speakers else None,
                progress_callback=progress,
            )
            if speaker_map:
                for seg in translation_result.segments:
                    label = speaker_map.get(seg.index, "")
                    if label:
                        seg.original = f"[{label}] {seg.original}"
                        seg.translated = f"[{label}] {seg.translated}"
                _log(
                    job_id,
                    f"[4.5] Diarization complete [{_time.time()-t:.1f}s] → {len(speaker_map)} segments labeled",
                )
            else:
                _log(job_id, f"[4.5] Diarization skipped (single speaker or failed)")

        # Step 5: 저장
        _update(job_id, "Saving files...", 95)
        _log(job_id, f"[5/5] Saving files (formats: {req.formats})...")
        t = _time.time()
        format_result = format_and_save(
            translation_result,
            output_name=output_name,
            formats=req.formats,
            export_dir=Path(req.export_dir) if req.export_dir else None,
            use_claude_summary=req.use_summary,
            progress_callback=progress,
        )

        filenames = [Path(f).name for f in format_result.saved_files]
        total_elapsed = _time.time() - total_start
        m, s = divmod(int(total_elapsed), 60)

        _log(job_id, f"[5/5] Saved {len(filenames)} files [{t:.1f}s]")
        _log(job_id, f"✅ Done! Total: {m}m {s}s")

        _update(
            job_id,
            "Done!",
            100,
            status="done",
            files=filenames,
            summary=format_result.claude_summary,
        )

    except Exception as e:
        _log(job_id, f"❌ Error: {e}")
        _update(job_id, f"Error: {e}", 0, status="error", error=str(e))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("VOXSCRIPT_PORT", 8765))
    print(f"[VOXScript] API server starting: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
