/**
 * resources/bin/ 에 필요한 외부 바이너리(ffmpeg, ffprobe, yt-dlp, deno)가
 * 없으면 자동으로 다운로드해서 채워 넣는 스크립트.
 *
 * 사용법: node scripts/fetch-binaries.js
 */

const fs = require("fs");
const path = require("path");
const https = require("https");
const { execSync } = require("child_process");

const BIN_DIR = path.join(__dirname, "..", "resources", "bin");
const TMP_DIR = path.join(__dirname, "..", ".bin-tmp");

function download(url, destPath) {
    return new Promise((resolve, reject) => {
        const request = (u) => {
            https.get(u, { headers: { "User-Agent": "voxscript-setup" } }, (res) => {
                // GitHub 릴리즈는 302로 실제 CDN URL로 리다이렉트함
                if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                    request(res.headers.location);
                    return;
                }
                if (res.statusCode !== 200) {
                    reject(new Error(`다운로드 실패 (${res.statusCode}): ${u}`));
                    return;
                }
                const file = fs.createWriteStream(destPath);
                res.pipe(file);
                file.on("finish", () => file.close(resolve));
            }).on("error", reject);
        };
        request(url);
    });
}

function unzip(zipPath, outDir) {
    fs.mkdirSync(outDir, { recursive: true });
    execSync(
        `powershell -NoProfile -Command "Expand-Archive -Path '${zipPath}' -DestinationPath '${outDir}' -Force"`,
        { stdio: "inherit" }
    );
}

function findFileRecursive(dir, filename) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            const found = findFileRecursive(full, filename);
            if (found) return found;
        } else if (entry.name.toLowerCase() === filename.toLowerCase()) {
            return full;
        }
    }
    return null;
}

async function ensure(name, checkFn) {
    const target = path.join(BIN_DIR, `${name}.exe`);
    if (fs.existsSync(target)) {
        console.log(`[fetch-binaries] ${name}.exe 이미 있음, 건너뜀`);
        return;
    }
    console.log(`[fetch-binaries] ${name}.exe 없음 → 다운로드 시작`);
    await checkFn(target);
    console.log(`[fetch-binaries] ${name}.exe 준비 완료`);
}

async function main() {
    fs.mkdirSync(BIN_DIR, { recursive: true });
    fs.mkdirSync(TMP_DIR, { recursive: true });

    // yt-dlp: 단일 exe
    await ensure("yt-dlp", async (target) => {
        await download(
            "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
            target
        );
    });

    // deno: zip 안에 deno.exe 하나
    await ensure("deno", async (target) => {
        const zipPath = path.join(TMP_DIR, "deno.zip");
        await download(
            "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
            zipPath
        );
        const extractDir = path.join(TMP_DIR, "deno-extract");
        unzip(zipPath, extractDir);
        const found = findFileRecursive(extractDir, "deno.exe");
        if (!found) throw new Error("압축 해제 후 deno.exe를 못 찾음");
        fs.copyFileSync(found, target);
    });

    // ffmpeg + ffprobe: BtbN 빌드 zip 하나에 둘 다 들어있음
    const needFfmpeg = !fs.existsSync(path.join(BIN_DIR, "ffmpeg.exe"));
    const needFfprobe = !fs.existsSync(path.join(BIN_DIR, "ffprobe.exe"));
    if (needFfmpeg || needFfprobe) {
        console.log("[fetch-binaries] ffmpeg/ffprobe 없음 → 다운로드 시작 (용량 커서 시간 걸림)");
        const zipPath = path.join(TMP_DIR, "ffmpeg.zip");
        await download(
            "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
            zipPath
        );
        const extractDir = path.join(TMP_DIR, "ffmpeg-extract");
        unzip(zipPath, extractDir);
        const ffmpegExe = findFileRecursive(extractDir, "ffmpeg.exe");
        const ffprobeExe = findFileRecursive(extractDir, "ffprobe.exe");
        if (!ffmpegExe || !ffprobeExe) throw new Error("압축 해제 후 ffmpeg/ffprobe를 못 찾음");
        fs.copyFileSync(ffmpegExe, path.join(BIN_DIR, "ffmpeg.exe"));
        fs.copyFileSync(ffprobeExe, path.join(BIN_DIR, "ffprobe.exe"));
        console.log("[fetch-binaries] ffmpeg.exe / ffprobe.exe 준비 완료");
    } else {
        console.log("[fetch-binaries] ffmpeg.exe / ffprobe.exe 이미 있음, 건너뜀");
    }

    fs.rmSync(TMP_DIR, { recursive: true, force: true });
    console.log("[fetch-binaries] 전체 완료");
}

main().catch((e) => {
    console.error("[fetch-binaries] 실패:", e.message);
    process.exit(1);
});