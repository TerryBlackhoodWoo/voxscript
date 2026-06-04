"""
VOXScript - Downloader
Supports: YouTube URL / Google Drive file or folder link / local file
"""

import os
import re
import io
import subprocess
import time
from pathlib import Path

DEFAULT_IMPORT_DIR = Path.home() / "Downloads" / "VOXScript" / "temp"
CREDENTIALS_PATH = Path(__file__).parent.parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "token.json"

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def is_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_gdrive_url(url: str) -> bool:
    return bool(re.search(r"drive\.google\.com", url))


def extract_gdrive_file_id(url: str) -> str | None:
    """파일 링크에서 ID 추출"""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def extract_gdrive_folder_id(url: str) -> str | None:
    """폴더 링크에서 ID 추출"""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def _get_gdrive_service():
    """Google Drive API 서비스 객체 반환 (OAuth 인증)"""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GDRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_PATH}\n"
                    "Download it from Google Cloud Console > APIs > Credentials > OAuth 2.0 Client IDs"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), GDRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _gdrive_download_file(
    service, file_id: str, output_path: Path, mime_type: str = ""
) -> Path:
    """Drive API로 파일 다운로드 후 mp3 변환"""
    from googleapiclient.http import MediaIoBaseDownload

    # 파일 메타데이터 조회
    meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    name = meta.get("name", "audio")
    mime = meta.get("mimeType", "")
    print(f"[Downloader] Downloading: {name} ({mime})")

    # 음원/영상 파일 다운로드
    raw_path = output_path.parent / f"_raw_{file_id}{_ext_from_mime(mime)}"
    request = service.files().get_media(fileId=file_id)

    with open(raw_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"\r  {int(status.progress() * 100)}%", end="", flush=True)
    print()

    # mp3 변환
    if str(raw_path).endswith(".mp3"):
        raw_path.rename(output_path)
    else:
        _convert_to_mp3(str(raw_path), output_path)
        raw_path.unlink(missing_ok=True)

    return output_path


def _ext_from_mime(mime: str) -> str:
    mapping = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-matroska": ".mkv",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/wav": ".wav",
    }
    return mapping.get(mime, ".mp4")


def download_audio(
    source: str,
    output_name: str = "audio",
    import_dir: Path | None = None,
) -> Path:
    work_dir = Path(import_dir) if import_dir else DEFAULT_IMPORT_DIR
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = work_dir / f"{output_name}.mp3"

    # ── 로컬 파일 ──────────────────────────────────────
    if os.path.exists(source):
        print(f"[Downloader] Local file: {source}")
        if source.endswith(".mp3"):
            return Path(source)
        _convert_to_mp3(source, output_path)
        return output_path

    # ── Google Drive ───────────────────────────────────
    if is_gdrive_url(source):
        service = _get_gdrive_service()

        folder_id = extract_gdrive_folder_id(source)
        file_id = extract_gdrive_file_id(source)

        if folder_id:
            # 폴더 안 음원/영상 파일 목록 조회
            print(f"[Downloader] Google Drive folder: {folder_id}")
            query = (
                f"'{folder_id}' in parents and trashed=false and ("
                "mimeType contains 'video/' or mimeType contains 'audio/')"
            )
            results = (
                service.files()
                .list(
                    q=query,
                    fields="files(id, name, mimeType)",
                    orderBy="name",
                )
                .execute()
            )
            files = results.get("files", [])

            if not files:
                raise ValueError(f"No audio/video files found in folder: {folder_id}")

            if len(files) == 1:
                f = files[0]
                print(f"[Downloader] Found 1 file: {f['name']}")
                return _gdrive_download_file(service, f["id"], output_path)
            else:
                # 여러 파일 → 순서대로 다운로드 후 병합
                print(f"[Downloader] Found {len(files)} files, downloading all...")
                part_paths = []
                for i, f in enumerate(files):
                    part_path = work_dir / f"_part_{i:03d}.mp3"
                    _gdrive_download_file(service, f["id"], part_path)
                    part_paths.append(part_path)

                # ffmpeg concat
                list_file = work_dir / "_concat_list.txt"
                list_file.write_text(
                    "\n".join(f"file '{p}'" for p in part_paths), encoding="utf-8"
                )
                subprocess.run(
                    [
                        "ffmpeg",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(list_file),
                        "-c",
                        "copy",
                        str(output_path),
                        "-y",
                    ],
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                )
                for p in part_paths:
                    p.unlink(missing_ok=True)
                list_file.unlink(missing_ok=True)
                return output_path

        elif file_id:
            print(f"[Downloader] Google Drive file: {file_id}")
            return _gdrive_download_file(service, file_id, output_path)

        else:
            raise ValueError(f"Cannot extract file/folder ID from: {source}")

    # ── YouTube ────────────────────────────────────────
    if is_youtube_url(source):
        print(f"[Downloader] YouTube audio extracting...")
        result = subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "-o",
                str(work_dir / f"{output_name}.%(ext)s"),
                source,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")
        print(f"[Downloader] Done: {output_path}")
        return output_path

    raise ValueError(f"Unsupported source format: {source}")


def _convert_to_mp3(input_path: str, output_path: Path):
    print(f"[Downloader] Converting to mp3: {input_path}")
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_path),
            "-y",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",  # ← 이거 추가
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
