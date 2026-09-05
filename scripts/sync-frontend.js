const fs = require("fs");
const path = require("path");

const src = path.join(__dirname, "..", "..", "voxscript_frontend", "dist");
const dest = path.join(__dirname, "..", "frontend", "dist");

if (!fs.existsSync(src)) {
    console.error(`[sync-frontend] 소스 없음: ${src} (먼저 voxscript_frontend에서 yarn build 필요)`);
    process.exit(1);
}

fs.rmSync(dest, { recursive: true, force: true });
fs.cpSync(src, dest, { recursive: true });
console.log(`[sync-frontend] ${src} → ${dest} 복사 완료`);