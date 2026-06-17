"""
VOXScript - 외부 바이너리(ffmpeg/ffprobe/yt-dlp) 경로 해석

Electron 패키징 빌드에서는 main.js가 FFMPEG_PATH / FFPROBE_PATH / YTDLP_PATH
환경변수로 번들된 바이너리의 절대경로를 넘겨준다.
개발 모드(env var 없음)에서는 시스템 PATH에서 찾고, 그것도 없으면 원래 이름을
그대로 반환해서 subprocess가 명확한 FileNotFoundError를 던지게 한다.
"""

import os
import shutil


def _resolve(env_key: str, exe_name: str) -> str:
    env_path = os.environ.get(env_key)
    if env_path and os.path.exists(env_path):
        return env_path

    found = shutil.which(exe_name)
    if found:
        return found

    # PATH에도 없으면 이름 그대로 반환 → 호출부에서 바로 에러로 드러남
    return exe_name


def get_ffmpeg() -> str:
    return _resolve("FFMPEG_PATH", "ffmpeg")


def get_ffmpeg_dir() -> str | None:
    """yt-dlp의 --ffmpeg-location용. 번들된 ffmpeg(FFMPEG_PATH)일 때만 디렉토리를 반환,
    PATH 검색/폴백인 경우엔 None을 반환해서 yt-dlp 자체 탐색 로직을 건드리지 않음."""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        from pathlib import Path

        return str(Path(env_path).parent)
    return None


def get_ffprobe() -> str:
    return _resolve("FFPROBE_PATH", "ffprobe")


def get_ytdlp() -> str:
    return _resolve("YTDLP_PATH", "yt-dlp")
