/* Share hand-off logic (no DOM), used by share.js in the browser and by tests/share.test.mjs in Node.
 *
 * Clip Studio never posts for you: "Share" downloads the MP4, copies the caption and opens the
 * platform's own upload page so you can drag the file in.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ShareCore = api;
})(typeof self !== "undefined" ? self : this, function () {
  // Upload pages (checked Nov 2026): youtube.com/upload → YouTube Studio's upload screen;
  // TikTok's web uploader lives in TikTok Studio; Instagram has no upload URL — use "+ Create".
  const PLATFORMS = {
    tiktok: { label: "TikTok", url: "https://www.tiktok.com/tiktokstudio/upload", tip: "" },
    instagram: { label: "Instagram", url: "https://www.instagram.com/",
                 tip: "Instagram has no direct upload page: click the + Create button (left menu), then Post → drag the video in." },
    youtube: { label: "YouTube", url: "https://www.youtube.com/upload", tip: "" },
  };

  // Official limits (Nov 2026). Only used for gentle, non-blocking notes.
  //  YouTube Shorts: up to 3 minutes, square or vertical (YouTube Help 12779649); uploads ≤ 256 GB.
  //  TikTok web upload: MP4/WebM, ≥ 720×1280, up to 30 minutes, under 10 GB (TikTok Help "creator tools").
  //  Instagram: reels over 3 minutes aren't recommended to new audiences (Instagram creators FAQ).
  const LIMITS = {
    youtube: { maxSeconds: 180, maxBytes: 256e9 },
    tiktok: { maxSeconds: 30 * 60, maxBytes: 10e9 },
    instagram: { maxSeconds: 180, maxBytes: null },
  };

  function slugify(text) {
    return String(text || "")
      .normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .toLowerCase().replace(/['"’]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
      .slice(0, 50).replace(/-+$/g, "");
  }

  /** clip-studio-<title>.mp4 — safe on Windows and macOS. */
  function shareFilename(title, id) {
    const s = slugify(title);
    return `clip-studio-${s || "clip-" + (id ?? "video")}.mp4`;
  }

  /** "#gta6 lacy, #shorts" → ["#gta6", "#lacy", "#shorts"] (deduplicated, case-insensitive). */
  function normalizeHashtags(text) {
    const seen = new Set();
    const out = [];
    String(text || "").split(/[\s,]+/).forEach((raw) => {
      const w = raw.replace(/^#+/, "").replace(/[^\p{L}\p{N}_]/gu, "");
      if (!w || seen.has(w.toLowerCase())) return;
      seen.add(w.toLowerCase());
      out.push("#" + w);
    });
    return out;
  }

  /** Caption text + hashtags, with hashtags already in the caption not repeated. */
  function composeCaption(caption, hashtags) {
    const body = String(caption || "").trim();
    const present = new Set((body.match(/#[\p{L}\p{N}_]+/gu) || []).map((t) => t.toLowerCase()));
    const tags = normalizeHashtags(hashtags).filter((t) => !present.has(t.toLowerCase()));
    return [body, tags.join(" ")].filter(Boolean).join("\n\n");
  }

  function fmtLen(sec) {
    const s = Math.round(sec);
    return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} min` : `${s}s`;
  }

  /** Non-blocking notes about format, length and size. info: {width, height, duration, size, codec}. */
  function videoNotes(info, platform) {
    const notes = [];
    const { width, height, duration, size } = info || {};
    if (width && height) {
      const vertical = Math.abs(width / height - 9 / 16) < 0.02;
      if (!vertical) notes.push(`This video is ${width}×${height}. TikTok, Reels and Shorts work best in vertical 9:16 (1080×1920).`);
    }
    const names = { youtube: "YouTube Shorts", tiktok: "TikTok", instagram: "Instagram Reels" };
    const list = platform ? [platform] : Object.keys(LIMITS);
    list.forEach((p) => {
      const lim = LIMITS[p];
      if (!lim) return;
      if (duration && duration > lim.maxSeconds) {
        if (p === "youtube") notes.push(`${fmtLen(duration)} is longer than 3 minutes, so YouTube will upload it as a regular video, not a Short.`);
        else if (p === "instagram") notes.push(`Reels over 3 minutes aren't recommended to new audiences on Instagram (this one is ${fmtLen(duration)}).`);
        else notes.push(`TikTok web uploads are limited to 30 minutes (this one is ${fmtLen(duration)}).`);
      }
      if (size && lim.maxBytes && size > lim.maxBytes) notes.push(`The file is too large for ${names[p]} (${(size / 1e9).toFixed(1)} GB).`);
    });
    return notes;
  }

  /**
   * One click on a platform button. Everything runs synchronously inside the click, in this order:
   *   1. open the upload page in a new tab — first, before anything slow, so popup blockers allow it
   *   2. start the MP4 download (same-origin link with Content-Disposition: attachment)
   *   3. copy the caption (the copy is started inside the same click, while it still counts as a user action)
   * deps: { open(url) → window|null, download(url, filename), copy(text) → Promise<boolean> }
   * Returns { platform, opened, popupBlocked, tip, copied: Promise<boolean> }.
   */
  function handoff(platform, video, caption, deps) {
    const p = PLATFORMS[platform];
    if (!p) throw new Error("Unknown platform: " + platform);
    let win = null;
    try { win = deps.open(p.url); } catch (e) { win = null; }
    deps.download(video.url, video.filename);
    let copied;
    try { copied = Promise.resolve(caption ? deps.copy(caption) : false).catch(() => false); }
    catch (e) { copied = Promise.resolve(false); }
    return { platform, url: p.url, opened: !!win, popupBlocked: !win, tip: p.tip, copied };
  }

  /** "Download" button: just the file. */
  function downloadOnly(video, deps) {
    deps.download(video.url, video.filename);
    return { downloaded: true };
  }

  function instructions(result, label) {
    const where = result.popupBlocked
      ? `Your browser blocked the new tab — use the “Open ${label} upload page” link below.`
      : `Drag it into the ${label} upload page that just opened.`;
    const lines = [`Your video downloaded. ${where}`];
    lines.push(result.copiedOk === false
      ? "Copying the caption didn't work here — use the Copy caption button, then paste it in."
      : "Your caption is copied, so paste it in.");
    if (result.tip) lines.push(result.tip);
    return lines;
  }

  return { PLATFORMS, LIMITS, slugify, shareFilename, normalizeHashtags, composeCaption, videoNotes, handoff,
           downloadOnly, instructions };
});
