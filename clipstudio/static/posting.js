/* Shared helpers for multi-account posting pages: badges, the originality checklist, assignment cards. */
(function () {
  const P = { youtube: "YouTube Shorts", tiktok: "TikTok", instagram: "Instagram Reels" };
  const PI = { youtube: "▶", tiktok: "♪", instagram: "◎" };
  const S = { raw: "Raw", edited: "Edited", scheduled: "Scheduled", posted: "Posted" };
  const esc = (s) => CS.esc(s);
  const fmtNum = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n || 0));

  function badge(a, opts = {}) {
    if (!a) return "";
    return `<span class="acct-badge" style="--c:${esc(a.color)}" title="${esc(P[a.platform])}${a.niche ? " · " + esc(a.niche) : ""}">
      <span class="pi">${PI[a.platform] || ""}</span>${esc(a.handle)}${opts.niche && a.niche ? `<span class="niche">${esc(a.niche)}</span>` : ""}</span>`;
  }

  // ---------- originality checklist dialog (one per page)
  let dlg;
  function ensureDialog() {
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.className = "card";
    dlg.innerHTML = `<h3>Originality checklist</h3>
      <p class="muted small">Platforms demonetize straight re-uploads. Tick each box only when it's really done — a clip can't be marked <b>Edited (ready)</b> until all three are ticked.</p>
      <div class="ck-items"></div>
      <div class="row" style="margin-top:12px"><button class="primary" data-ck="save">Save</button><button data-ck="close">Cancel</button>
      <a class="btn small ghost" data-ck="review" href="#">Edit clip on Review page →</a></div>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("click", (e) => { if (e.target.dataset.ck === "close") dlg.close(); });
    return dlg;
  }
  async function openChecklist(clipId) {
    const d = ensureDialog();
    const data = await CS.api("GET", `/api/clips/${clipId}/checklist`);
    d.querySelector(".ck-items").innerHTML = Object.entries(data.labels).map(([k, label]) => `
      <label class="ck-row"><input type="checkbox" data-k="${k}" ${data.checklist[k] ? "checked" : ""}>
        <span><b>${esc(label)}</b>${data.hints[k] ? `<br><span class="muted small">💡 ${esc(data.hints[k])}</span>` : ""}</span></label>`).join("");
    d.querySelector('[data-ck="review"]').href = `/review?clip=${clipId}`;
    d.showModal();
    return new Promise((resolve) => {
      const save = d.querySelector('[data-ck="save"]');
      save.onclick = async () => {
        const body = {};
        d.querySelectorAll("[data-k]").forEach((i) => (body[i.dataset.k] = i.checked));
        try { const r = await CS.api("PUT", `/api/clips/${clipId}/checklist`, body); d.close(); resolve(r.checklist); }
        catch (e) { CS.toast(e.message, "error"); }
      };
      d.addEventListener("close", () => resolve(null), { once: true });
    });
  }

  function warningsHtml(ws) {
    return ws && ws.length ? `<div class="warnings small">⚠ ${ws.map(esc).join("<br>⚠ ")}</div>` : "";
  }
  /* Pop up only warnings that aren't already visible (e.g. the daily limit), in one toast. */
  function showWarnings(ws, already = []) {
    const fresh = (ws || []).filter((w) => !already.includes(w));
    if (fresh.length) CS.toast("⚠ " + fresh.join("\n⚠ "), "warn", 10000);
  }

  function localInputValue(s) { return s ? s.replace(" ", "T") : ""; }
  function defaultSchedule() {
    const d = new Date(Date.now() + 3600e3); d.setMinutes(0, 0, 0);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
  }

  /* A pipeline card for one clip-on-account assignment, with the actions for its current status. */
  function card(a) {
    const c = a.clip || {};
    const ck = c.checklist || {};
    const nTicked = Object.values(ck).filter(Boolean).length;
    let actions = "";
    if (a.status === "raw") {
      actions = `<button class="small" data-act="checklist">☑ Checklist ${nTicked}/3</button>
        <button class="small okb" data-act="move" data-to="edited">Mark edited →</button>`;
    } else if (a.status === "edited") {
      actions = `<input type="datetime-local" class="sched-in" value="${esc(localInputValue(a.scheduled_at) || defaultSchedule())}">
        <button class="small okb" data-act="schedule">Schedule →</button>
        <button class="small ghost" data-act="move" data-to="raw">← Raw</button>`;
    } else if (a.status === "scheduled") {
      actions = `<div class="muted small">🗓 ${esc(a.scheduled_at)}</div>
        <input type="url" class="url-in" placeholder="Post link (optional)">
        <button class="small okb" data-act="post">Mark posted ✔</button>
        <button class="small ghost" data-act="move" data-to="edited">← Unschedule</button>`;
    } else {
      actions = `${a.post_url ? `<a class="small" href="${esc(a.post_url)}" target="_blank" rel="noopener">Open post ↗</a>` : ""}
        <div class="stats-row"><label>Views <input type="text" inputmode="numeric" class="views-in" value="${a.views || 0}"></label>
        <label>Earnings $ <input type="text" inputmode="decimal" class="earn-in" value="${a.earnings || 0}"></label>
        <button class="small" data-act="stats">Save</button></div>
        <button class="small ghost" data-act="move" data-to="scheduled">← Not posted yet</button>`;
    }
    return `<div class="pcard" data-id="${a.id}" data-clip="${c.id}" data-w="${esc(JSON.stringify(a.warnings || []))}">
      <div class="pcard-top">
        ${c.thumb_url ? `<img src="${esc(c.thumb_url)}" alt="" loading="lazy">` : `<div class="noimg"></div>`}
        <div class="pcard-meta">
          ${badge(a.account)}
          <div class="pcard-title">${esc(c.title || "Clip #" + c.id)}</div>
          <div class="muted small">${esc(c.streamer || "")} · ${CS.fmtDur(c.length)} · <a href="/review?clip=${c.id}">clip #${c.id}</a></div>
        </div>
        <button class="small ghost x" data-act="unassign" title="Remove from this account">✕</button>
      </div>
      ${warningsHtml(a.warnings)}
      <div class="pcard-actions">${actions}</div></div>`;
  }

  /* Handles clicks on pipeline cards; calls refresh() after any change. */
  function bindCards(root, refresh) {
    root.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]");
      const el = e.target.closest(".pcard");
      if (!b || !el) return;
      const id = el.dataset.id;
      const before = JSON.parse(el.dataset.w || "[]");
      try {
        let r;
        if (b.dataset.act === "checklist") { if (await openChecklist(el.dataset.clip)) refresh(); return; }
        if (b.dataset.act === "move") r = await CS.api("POST", `/api/assignments/${id}/status`, { status: b.dataset.to });
        if (b.dataset.act === "schedule") r = await CS.api("POST", `/api/assignments/${id}/status`, { status: "scheduled", scheduled_at: el.querySelector(".sched-in").value });
        if (b.dataset.act === "post") r = await CS.api("POST", `/api/assignments/${id}/status`, { status: "posted", post_url: el.querySelector(".url-in").value });
        if (b.dataset.act === "stats") { await CS.api("POST", `/api/assignments/${id}/stats`, { views: el.querySelector(".views-in").value, earnings: el.querySelector(".earn-in").value }); CS.toast("Saved", "ok", 1500); refresh(); return; }
        if (b.dataset.act === "unassign") { if (!confirm("Remove this clip from the account?")) return; await CS.api("DELETE", `/api/assignments/${id}`); }
        if (r) showWarnings(r.warnings, before);
        refresh();
      } catch (err) {
        CS.toast(err.message, "error", 9000);
        if (/checklist/i.test(err.message)) { if (await openChecklist(el.dataset.clip)) refresh(); }
      }
    });
  }

  Object.assign(CS, { PLATFORMS: P, PICONS: PI, STATUSES: S, acctBadge: badge, openChecklist, assignmentCard: card,
    bindCards, showWarnings, fmtNum });
})();
