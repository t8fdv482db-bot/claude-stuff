/* Review grid: approve/reject, edit title/description/hook, trim + re-render, keyboard shortcuts, posting. */
(function () {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  let status = params.has("clip") ? "" : (params.get("status") ?? "pending");
  let clips = [];
  let sel = 0;
  if (params.get("job")) $("f-job").value = params.get("job");
  if (params.get("streamer")) $("f-streamer").value = params.get("streamer");
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.status === status));

  async function load() {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if ($("f-streamer").value) q.set("streamer_id", $("f-streamer").value);
    if ($("f-job").value) q.set("job_id", $("f-job").value);
    const d = await CS.api("GET", "/api/clips?" + q);
    clips = d.clips;
    render();
    const focus = Number(params.get("clip"));
    if (focus) { const i = clips.findIndex((c) => c.id === focus); if (i >= 0) select(i); }
    counts();
  }
  async function counts() {
    const d = await CS.api("GET", "/api/clips/counts");
    document.querySelectorAll("[data-count]").forEach((el) => (el.textContent = d[el.dataset.count] || ""));
    CS.updatePending();
  }

  function countdownHtml(c) {
    const post = (c.posts || []).filter((p) => !p.submitted).slice(-1)[0];
    if (!post || !c.campaign) return "";
    const deadline = (post.posted_at + c.campaign.submit_window_min * 60) * 1000;
    return `<div class="countdown" data-deadline="${deadline}"><span class="cd-text"></span>
      ${c.campaign.submit_url ? `<a class="btn small" target="_blank" rel="noopener" href="${CS.esc(c.campaign.submit_url)}">Open submit page</a>` : ""}
      <button class="small okb" data-act="submitted" data-post="${post.id}">Submitted ✔</button></div>`;
  }

  function card(c) {
    const busy = c.render_state === "queued" || c.render_state === "rendering";
    const sig = Object.entries(c.signals || {}).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(" · ");
    const yt = c.youtube_id ? `<a href="https://youtu.be/${c.youtube_id}" target="_blank" rel="noopener">YouTube ✓</a> ${c.publish_at ? "· goes public " + new Date(c.publish_at).toLocaleString() : ""}`
      : c.yt_state === "retry" ? `<span class="warn">YouTube: ${CS.esc(c.yt_error || "will retry")}</span>`
      : c.yt_state === "error" ? `<span class="err">YouTube: ${CS.esc(c.yt_error || "failed")}</span>` : "";
    return `<div class="clip" data-id="${c.id}">
      <div class="player">
        ${c.video_url ? `<video src="${c.video_url}" poster="${c.thumb_url || ""}" preload="none" controls playsinline loop></video>` : `<img alt="" src="${c.thumb_url || "data:,"}">`}
        ${busy ? `<div class="spinner"><div><div class="spin"></div>${c.render_state === "queued" ? "Waiting to render…" : "Rendering…"}</div></div>` : ""}
        ${c.render_state === "error" ? `<div class="spinner"><div class="err" style="padding:16px">Render failed:<br>${CS.esc(c.render_error || "")}<br><button data-act="rerender">Retry</button></div></div>` : ""}
      </div>
      <div class="body">
        <div class="meta">
          <span class="st-${c.status}">● ${c.status}</span>
          <span>${CS.fmtDur(c.length)}</span>
          <span class="score" title="${CS.esc(sig)}">score ${Number(c.score || 0).toFixed(2)}</span>
          ${c.ai_score ? `<span class="score">AI ${c.ai_score}/10</span>` : ""}
          <span title="Source time">@ ${CS.fmtDur(c.start)}</span>
          <a href="/jobs/${c.job_id}">job #${c.job_id}</a>
        </div>
        ${c.reason ? `<div class="muted small">${CS.esc(c.reason)}</div>` : ""}
        ${(c.warnings || []).length ? `<div class="warnings">⚠ ${c.warnings.map(CS.esc).join("<br>⚠ ")}</div>` : ""}
        ${countdownHtml(c)}
        <input type="text" class="title-in" data-field="title" maxlength="100" value="${CS.esc(c.title)}" placeholder="Title">
        <div class="row" style="gap:6px"><input type="text" data-field="hook" value="${CS.esc(c.hook)}" placeholder="Hook text (first 3 s)" style="flex:1"><button class="small" data-act="hook">Apply</button></div>
        <textarea data-field="description" rows="3" placeholder="Description / caption">${CS.esc(c.description)}</textarea>
        <div class="trim">
          <span class="muted small">Start</span><button class="small" data-act="trim" data-s="-1">−1s</button><button class="small" data-act="trim" data-s="1">+1s</button>
          <span class="muted small">End</span><button class="small" data-act="trim" data-e="-1">−1s</button><button class="small" data-act="trim" data-e="1">+1s</button>
          <button class="small" data-act="trim" data-e="5">Extend 5s</button>
        </div>
        <div class="actions">
          <button class="small okb" data-act="approve">✔ Approve</button>
          <button class="small danger" data-act="reject">✕ Reject</button>
          <button class="small" data-act="regen" title="Ask the AI for a new title">✨ New title</button>
          <button class="small" data-act="posted">Mark posted…</button>
          ${c.video_url ? `<a class="btn small" href="/api/clips/${c.id}/download">⬇ MP4</a><a class="btn small" href="/api/clips/${c.id}/caption.txt">⬇ Caption</a>` : ""}
        </div>
        ${yt ? `<div class="small">${yt}</div>` : ""}
      </div></div>`;
  }

  function render() {
    $("grid").innerHTML = clips.map(card).join("");
    $("empty").classList.toggle("hidden", clips.length > 0);
    sel = Math.min(sel, Math.max(0, clips.length - 1));
    highlight();
    tick();
  }
  function replaceCard(c) {
    const i = clips.findIndex((x) => x.id === c.id);
    if (i < 0) return;
    const el = document.querySelector(`.clip[data-id="${c.id}"]`);
    const playing = el?.querySelector("video") && !el.querySelector("video").paused;
    clips[i] = c;
    const typing = el && el.contains(document.activeElement) && document.activeElement.matches("input, textarea");
    if (el && !playing && !typing) {
      el.outerHTML = card(c);
      highlight();
      tick();
    }
  }
  function highlight() {
    document.querySelectorAll(".clip").forEach((el, i) => el.classList.toggle("sel", i === sel));
  }
  function select(i) {
    if (!clips.length) return;
    sel = Math.max(0, Math.min(clips.length - 1, i));
    highlight();
    document.querySelectorAll(".clip")[sel]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function act(id, action, el) {
    const c = clips.find((x) => x.id === id);
    if (!c) return;
    try {
      if (action === "approve" || action === "reject") {
        const st = action === "approve" ? "approved" : "rejected";
        const r = await CS.api("PATCH", `/api/clips/${id}`, { status: c.status === st ? "pending" : st });
        if (status && r.status !== status) {
          const i = clips.findIndex((x) => x.id === id);
          clips.splice(i, 1);
          render();
          select(i);
        } else replaceCard(Object.assign(r, {}));
        counts();
      } else if (action === "trim") {
        const r = await CS.api("POST", `/api/clips/${id}/trim`, { start_delta: Number(el.dataset.s || 0), end_delta: Number(el.dataset.e || 0) });
        replaceCard(r);
      } else if (action === "hook") {
        const hook = document.querySelector(`.clip[data-id="${id}"] [data-field=hook]`).value;
        document.activeElement.blur();
        replaceCard(await CS.api("PATCH", `/api/clips/${id}`, { hook }));
      } else if (action === "regen") {
        el.disabled = true; el.textContent = "✨ Thinking…";
        const r = await CS.api("POST", `/api/clips/${id}/regen-title`);
        replaceCard(r);
      } else if (action === "rerender") {
        await CS.api("POST", `/api/clips/${id}/rerender`);
      } else if (action === "posted") {
        openPostDialog(id);
      } else if (action === "submitted") {
        await CS.api("PATCH", `/api/posts/${el.dataset.post}`, { submitted: true });
        replaceCard(await CS.api("GET", `/api/clips/${id}`));
        CS.toast("Marked as submitted ✔", "ok");
      }
    } catch (e) { CS.toast(e.message, "error"); el && (el.disabled = false); }
  }

  $("grid").addEventListener("click", (e) => {
    const cardEl = e.target.closest(".clip");
    if (!cardEl) return;
    const idx = [...document.querySelectorAll(".clip")].indexOf(cardEl);
    if (idx !== sel) { sel = idx; highlight(); }
    const b = e.target.closest("[data-act]");
    if (b) act(Number(cardEl.dataset.id), b.dataset.act, b);
  });
  $("grid").addEventListener("change", async (e) => {
    const f = e.target.dataset.field;
    if (!f || f === "hook") return;
    const id = Number(e.target.closest(".clip").dataset.id);
    try {
      const r = await CS.api("PATCH", `/api/clips/${id}`, { [f]: e.target.value });
      const i = clips.findIndex((x) => x.id === id);
      clips[i] = r;
      CS.toast("Saved", "ok", 1500);
    } catch (err) { CS.toast(err.message, "error"); }
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select") || e.ctrlKey || e.metaKey || e.altKey || $("post-dlg").open) return;
    const c = clips[sel];
    const k = e.key.toLowerCase();
    if (k === "j") { select(sel + 1); e.preventDefault(); }
    else if (k === "k") { select(sel - 1); e.preventDefault(); }
    else if (k === "a" && c) { act(c.id, "approve"); e.preventDefault(); }
    else if (k === "r" && c) { act(c.id, "reject"); e.preventDefault(); }
    else if (k === " " && c) {
      e.preventDefault();
      const v = document.querySelectorAll(".clip")[sel]?.querySelector("video");
      if (v) { document.querySelectorAll(".clip video").forEach((o) => o !== v && o.pause()); v.paused ? v.play() : v.pause(); }
    }
  });

  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
    status = b.dataset.status;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    sel = 0; load();
  }));
  $("f-streamer").addEventListener("change", load);
  $("f-job").addEventListener("change", load);

  // ----- posting + countdown
  let postClip = null;
  function openPostDialog(id) { postClip = id; $("post-url").value = ""; $("post-dlg").showModal(); $("post-url").focus(); }
  $("post-cancel").addEventListener("click", () => $("post-dlg").close());
  $("post-save").addEventListener("click", async () => {
    try {
      const r = await CS.api("POST", `/api/clips/${postClip}/posted`, { platform: $("post-platform").value, url: $("post-url").value });
      $("post-dlg").close();
      if (status && status !== "posted") { clips = clips.filter((c) => c.id !== postClip); render(); } else replaceCard(r);
      (r.warnings || []).forEach((w) => CS.toast(w, "error", 8000));
      counts();
    } catch (e) { CS.toast(e.message, "error"); }
  });
  function tick() {
    document.querySelectorAll(".countdown[data-deadline]").forEach((el) => {
      const left = Math.round((Number(el.dataset.deadline) - Date.now()) / 1000);
      const t = el.querySelector(".cd-text");
      if (left > 0) { t.textContent = `⏱ Submit within ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`; el.classList.remove("late"); }
      else { t.textContent = `⏱ Submit window passed ${CS.fmtDur(-left)} ago`; el.classList.add("late"); }
    });
  }
  setInterval(tick, 1000);

  $("schedule-approved").addEventListener("click", async () => {
    if (!confirm("Upload every approved clip (not yet on YouTube) as PRIVATE, scheduled into your next free slots?")) return;
    try {
      const r = await CS.api("POST", "/api/youtube/schedule-approved");
      CS.toast(r.message, r.ok ? "ok" : "error", 9000);
    } catch (e) { CS.toast(e.message, "error", 9000); }
  });

  CS.on("clip", (c) => {
    if (c._new) {
      const matches = (!status || c.status === status) && (!$("f-job").value || Number($("f-job").value) === c.job_id) && (!$("f-streamer").value || Number($("f-streamer").value) === c.streamer_id);
      if (matches && !clips.find((x) => x.id === c.id)) { clips.unshift(c); render(); }
      counts();
      return;
    }
    const old = clips.find((x) => x.id === c.id);
    if (old) replaceCard(Object.assign({}, old, c));
  });
  load();
})();
