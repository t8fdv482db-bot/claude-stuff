/* Share window: hand a finished clip to TikTok / Instagram / YouTube by hand.
 * Download the MP4 + copy the caption + open the platform's upload page. No logins, no posting.
 * Usage: CS.openShare(clipId, { platform: "tiktok" })  — platform just highlights a button.
 */
(function () {
  const SC = window.ShareCore;
  const esc = (s) => CS.esc(s);
  const ICONS = { tiktok: "♪", instagram: "◎", youtube: "▶" };   // generic symbols, not logos
  let dlg, current = null;

  function build() {
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.className = "card share-dlg";
    dlg.innerHTML = `
      <div class="share-head"><h3>Share clip</h3><button class="small ghost" data-sh="close" aria-label="Close">✕</button></div>
      <div class="share-body">
        <div class="share-thumb"><img alt=""><div class="share-meta muted small"></div></div>
        <div class="share-main">
          <label>Caption <textarea rows="4" data-sh="caption" placeholder="Write a caption (optional)"></textarea></label>
          <label>Hashtags <input type="text" data-sh="tags" placeholder="#gta6 #shorts"></label>
          <div class="row"><button class="small" data-sh="copy">📋 Copy caption</button>
            <span class="muted small">TikTok, Instagram and YouTube don't take a pre-filled caption, so you paste it in.</span></div>
          <div class="share-notes"></div>
        </div>
      </div>
      <div class="share-plats">
        ${Object.entries(SC.PLATFORMS).map(([k, p]) => `<button class="share-plat" data-plat="${k}"><span class="pi">${ICONS[k] || ""}</span>${p.label}</button>`).join("")}
        <button class="share-plat dl" data-sh="download">⬇ Download</button>
      </div>
      <div class="share-done hidden"></div>
      <p class="muted small share-foot">Clicking a platform downloads the video, copies your caption and opens that site's upload page.
        Clip Studio never logs in to your accounts or posts for you.</p>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("click", onClick);
    return dlg;
  }

  function caption() {
    return SC.composeCaption(dlg.querySelector('[data-sh="caption"]').value, dlg.querySelector('[data-sh="tags"]').value);
  }
  function video() {
    const filename = SC.shareFilename(current.title, current.id);
    return { url: `${current.download_url}?name=${encodeURIComponent(filename)}`, filename };
  }

  // Browser actions handed to ShareCore (kept tiny so the logic stays testable).
  const deps = {
    open: (url) => {
      // No "noopener" flag here: with it, window.open always returns null and we couldn't tell a blocked popup.
      const w = window.open(url, "_blank");
      if (w) { try { w.opener = null; } catch (e) { /* cross-origin already */ } }
      return w;
    },
    download: (url, filename) => {
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.rel = "noopener"; a.style.display = "none";
      document.body.appendChild(a); a.click(); a.remove();
    },
    copy: (text) => copyText(text),
  };

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
    }
    return Promise.resolve(legacyCopy(text));
  }
  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  function onClick(e) {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.sh === "close") { dlg.close(); return; }
    if (b.dataset.sh === "copy") {
      const text = caption();
      if (!text) { CS.toast("The caption is empty.", "error", 2500); return; }
      copyText(text).then((ok) => CS.toast(ok ? "Caption copied — paste it in the app." : "Couldn't copy — select the text and press Ctrl+C.", ok ? "ok" : "error", 3500));
      return;
    }
    if (b.dataset.sh === "download") {
      SC.downloadOnly(video(), deps);
      showDone(["Your video is downloading — check your Downloads folder."]);
      return;
    }
    const plat = b.dataset.plat;
    if (!plat) return;
    // Everything below happens synchronously inside this click (see ShareCore.handoff).
    const result = SC.handoff(plat, video(), caption(), deps);
    const label = SC.PLATFORMS[plat].label;
    result.copied.then((ok) => {
      result.copiedOk = caption() ? ok : true;
      showDone(SC.instructions(result, label), result.popupBlocked ? result.url : null, label);
    });
  }

  function showDone(lines, link, label) {
    const box = dlg.querySelector(".share-done");
    box.innerHTML = `<b>✔ Next:</b><ol>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ol>` +
      (link ? `<a class="btn small" href="${esc(link)}" target="_blank" rel="noopener">Open ${esc(label)} upload page ↗</a>` : "");
    box.classList.remove("hidden");
  }

  async function openShare(clipId, opts = {}) {
    build();
    current = null;
    dlg.querySelector(".share-done").classList.add("hidden");
    dlg.querySelector(".share-notes").innerHTML = "";
    dlg.querySelector(".share-meta").textContent = "Loading…";
    dlg.querySelector(".share-thumb img").removeAttribute("src");
    dlg.querySelectorAll(".share-plat").forEach((x) => { x.disabled = true; x.classList.toggle("suggested", x.dataset.plat === opts.platform); });
    if (!dlg.open) dlg.showModal();
    try {
      current = await CS.api("GET", `/api/clips/${clipId}/share-info`);
    } catch (e) {
      dlg.querySelector(".share-meta").innerHTML = `<span class="err">${esc(e.message)}</span> <button class="small" data-retry>Retry</button>`;
      dlg.querySelector("[data-retry]").onclick = () => openShare(clipId, opts);
      return;
    }
    dlg.querySelector(".share-thumb img").src = current.thumb_url || "";
    dlg.querySelector(".share-meta").textContent =
      `${current.width}×${current.height} · ${CS.fmtDur(current.duration)} · ${(current.size / 1e6).toFixed(1)} MB · MP4`;
    dlg.querySelector('[data-sh="caption"]').value = current.caption || "";
    dlg.querySelector('[data-sh="tags"]').value = current.hashtags || "";
    const notes = SC.videoNotes(current);
    if (!current.mp4) notes.unshift("This file isn't H.264/AAC MP4 — re-render the clip so every platform accepts it.");
    dlg.querySelector(".share-notes").innerHTML = notes.map((n) => `<div class="warnings small">ℹ ${esc(n)}</div>`).join("");
    dlg.querySelectorAll(".share-plat").forEach((x) => (x.disabled = false));
  }

  CS.openShare = openShare;
})();
