// Tests for the Share hand-off logic. Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const S = require("../clipstudio/static/share-core.js");

function fakeDeps({ popupBlocked = false, copyFails = false } = {}) {
  const calls = [];
  return {
    calls,
    open: (url) => { calls.push(["open", url]); return popupBlocked ? null : { closed: false }; },
    download: (url, name) => calls.push(["download", url, name]),
    copy: (text) => { calls.push(["copy", text]); return copyFails ? Promise.reject(new Error("Document is not focused")) : Promise.resolve(true); },
  };
}
const video = { url: "/api/clips/9/download?name=clip-studio-x.mp4", filename: "clip-studio-x.mp4" };

test("platform button: opens the upload page first, then downloads, then copies — all in the click", async () => {
  for (const [platform, url] of [["tiktok", "https://www.tiktok.com/tiktokstudio/upload"],
                                 ["youtube", "https://www.youtube.com/upload"],
                                 ["instagram", "https://www.instagram.com/"]]) {
    const deps = fakeDeps();
    const r = S.handoff(platform, video, "caption #gta6", deps);
    // synchronous: every step already happened before any await
    assert.deepEqual(deps.calls.map((c) => c[0]), ["open", "download", "copy"]);
    assert.equal(deps.calls[0][1], url);
    assert.deepEqual(deps.calls[1].slice(1), [video.url, video.filename]);
    assert.equal(r.opened, true);
    assert.equal(await r.copied, true);
  }
});

test("Instagram shows the + Create tip; others don't", () => {
  assert.match(S.handoff("instagram", video, "", fakeDeps()).tip, /\+ Create/);
  assert.equal(S.handoff("tiktok", video, "", fakeDeps()).tip, "");
});

test("popup blocked: still downloads and copies, and says so", async () => {
  const deps = fakeDeps({ popupBlocked: true });
  const r = S.handoff("youtube", video, "hi", deps);
  assert.equal(r.popupBlocked, true);
  assert.deepEqual(deps.calls.map((c) => c[0]), ["open", "download", "copy"]);
  assert.match(S.instructions({ ...r, copiedOk: await r.copied }, "YouTube")[0], /blocked/);
});

test("clipboard refused: never throws, instructions point to the Copy caption button", async () => {
  const r = S.handoff("tiktok", video, "hi", fakeDeps({ copyFails: true }));
  const ok = await r.copied;
  assert.equal(ok, false);
  const lines = S.instructions({ ...r, copiedOk: ok }, "TikTok");
  assert.match(lines.join(" "), /Copy caption button/);
});

test("open() throwing (e.g. strict popup settings) is treated as blocked", () => {
  const deps = fakeDeps();
  deps.open = () => { throw new Error("blocked"); };
  assert.equal(S.handoff("tiktok", video, "", deps).popupBlocked, true);
});

test("empty caption: nothing is copied", async () => {
  const deps = fakeDeps();
  const r = S.handoff("tiktok", video, "", deps);
  assert.equal(deps.calls.some((c) => c[0] === "copy"), false);
  assert.equal(await r.copied, false);
});

test("Download button only downloads", () => {
  const deps = fakeDeps();
  S.downloadOnly(video, deps);
  assert.deepEqual(deps.calls, [["download", video.url, video.filename]]);
});

test("unknown platform is an error", () => {
  assert.throws(() => S.handoff("myspace", video, "", fakeDeps()), /Unknown platform/);
});

test("instructions: normal case", () => {
  const lines = S.instructions({ popupBlocked: false, copiedOk: true, tip: "" }, "TikTok");
  assert.deepEqual(lines, ["Your video downloaded. Drag it into the TikTok upload page that just opened.",
                           "Your caption is copied, so paste it in."]);
});

test("filenames are safe and readable", () => {
  assert.equal(S.shareFilename('Lacy: "Can we run, man?"', 12), "clip-studio-lacy-can-we-run-man.mp4");
  assert.equal(S.shareFilename("Kai’s Ünïcode café ✨", 3), "clip-studio-kais-unicode-cafe.mp4");
  assert.equal(S.shareFilename("", 7), "clip-studio-clip-7.mp4");
  assert.equal(S.shareFilename("💀💀💀", 8), "clip-studio-clip-8.mp4");
  assert.ok(S.shareFilename("x".repeat(200), 1).length <= "clip-studio-.mp4".length + 50);
});

test("caption + hashtags: normalized, deduplicated, not repeated", () => {
  assert.equal(S.composeCaption("Lacy loses it", "gta6, #lacy #GTA6 shorts"), "Lacy loses it\n\n#gta6 #lacy #shorts");
  assert.equal(S.composeCaption("Already #gta6 here", "#gta6 #clip"), "Already #gta6 here\n\n#clip");
  assert.equal(S.composeCaption("", "#a"), "#a");
  assert.equal(S.composeCaption("just text", ""), "just text");
});

test("video notes: vertical 1080×1920 short clip has none", () => {
  assert.deepEqual(S.videoNotes({ width: 1080, height: 1920, duration: 45, size: 13e6 }), []);
});

test("video notes: non-vertical, long and huge files get gentle notes", () => {
  const wide = S.videoNotes({ width: 1920, height: 1080, duration: 30 });
  assert.equal(wide.length, 1);
  assert.match(wide[0], /9:16/);
  const long = S.videoNotes({ width: 1080, height: 1920, duration: 200 });
  assert.ok(long.some((n) => /not a Short/.test(n)));
  assert.ok(long.some((n) => /Instagram/.test(n)));
  assert.ok(!long.some((n) => /TikTok/.test(n)));                     // TikTok allows up to 30 min
  assert.ok(S.videoNotes({ duration: 31 * 60 }, "tiktok").some((n) => /30 minutes/.test(n)));
  assert.ok(S.videoNotes({ size: 11e9 }, "tiktok").some((n) => /too large/.test(n)));
});
