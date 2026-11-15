/* Home page: link input with platform badges, job options, live job list. */
(function () {
  const $ = (id) => document.getElementById(id);
  const STAGES = ["queued", "downloading", "chat", "transcribing", "scoring", "rendering", "done"];
  const jobs = new Map();
  const openLogs = new Set();
  const probeCache = new Map();

  // ---------- badges
  function quickDetect(url) {
    const u = url.toLowerCase();
    let platform = "unknown", kind = "VOD";
    if (/^(file:\/\/|\/|~\/|[a-z]:[\\/])/.test(u)) platform = "Local file";
    else if (/twitch\.tv/.test(u)) { platform = "Twitch"; kind = /\/videos?\/\d+|\/clip\/|clips\.twitch/.test(u) ? "VOD" : "LIVE"; }
    else if (/kick\.com/.test(u)) { platform = "Kick"; kind = /\/video\/|\/videos\/|\/clips?\//.test(u) ? "VOD" : "LIVE"; }
    else if (/youtube\.com|youtu\.be/.test(u)) { platform = "YouTube"; kind = /\/live(\/|$)/.test(u) ? "LIVE?" : "VOD"; }
    return { platform, kind };
  }
  let probeTimer;
  function renderBadges() {
    const lines = $("urls").value.split("\n").map((s) => s.trim()).filter(Boolean);
    $("badges").innerHTML = lines.map((url) => {
      const p = probeCache.get(url);
      const q = quickDetect(url);
      const label = p && p.ok ? p.badge : `${q.platform} · ${q.kind}`;
      const live = /LIVE/.test(label);
      const title = p && p.ok ? ` — ${CS.esc(p.title).slice(0, 70)}${p.duration ? " (" + CS.fmtDur(p.duration) + ")" : ""}` : (p && !p.ok ? " — couldn't check (will retry when the job runs)" : "");
      return `<div class="badge-row"><span class="badge ${q.platform === "unknown" ? "bad" : live ? "live" : ""}">${CS.esc(label)}</span><span class="muted small">${CS.esc(url).slice(0, 80)}${title}</span></div>`;
    }).join("");
    clearTimeout(probeTimer);
    probeTimer = setTimeout(() => lines.forEach(probe), 700);
  }
  async function probe(url) {
    if (probeCache.has(url) || ["unknown", "Local file"].includes(quickDetect(url).platform)) return;
    probeCache.set(url, null);
    try { probeCache.set(url, await CS.api("GET", "/api/probe?url=" + encodeURIComponent(url))); }
    catch (e) { probeCache.set(url, { ok: false }); }
    renderBadges();
  }
  $("urls").addEventListener("input", renderBadges);

  // ---------- streamer "+ New"
  $("opt-streamer").addEventListener("change", async (e) => {
    if (e.target.value !== "__new") return;
    const name = prompt("Streamer name?");
    if (!name) { e.target.value = ""; return; }
    try {
      const s = await CS.api("POST", "/api/streamers", { name });
      const opt = new Option(s.name, s.id);
      e.target.add(opt, e.target.options.length - 1);
      e.target.value = s.id;
    } catch (err) { CS.toast(err.message, "error"); e.target.value = ""; }
  });

  // ---------- submit
  $("go").addEventListener("click", async () => {
    const body = {
      urls: $("urls").value,
      streamer_id: $("opt-streamer").value && $("opt-streamer").value !== "__new" ? Number($("opt-streamer").value) : null,
      clip_count: Number($("opt-count").value), min_len: Number($("opt-min").value), max_len: Number($("opt-max").value),
      layout: $("opt-layout").value || null, campaign_id: $("opt-campaign").value ? Number($("opt-campaign").value) : null,
      ai: $("opt-ai").checked,
    };
    if (body.min_len >= body.max_len) { CS.toast("Min length must be shorter than max length.", "error"); return; }
    $("go").disabled = true;
    try {
      const r = await CS.api("POST", "/api/jobs", body);
      $("go-msg").textContent = `Started ${r.jobs.length} job${r.jobs.length > 1 ? "s" : ""}.`;
      $("urls").value = ""; renderBadges();
      r.jobs.forEach((j) => upsert(j));
    } catch (e) { CS.toast(e.message, "error"); }
    $("go").disabled = false;
  });

  // ---------- job list
  function elapsed(j) {
    if (!j.started) return "";
    const end = j.finished || Date.now() / 1000;
    return CS.fmtDur(end - j.started);
  }
  function stageChips(j) {
    if (j.is_live && (j.status === "watching" || j.stage === "watching")) return `<span class="chip on live">● watching live</span>`;
    const idx = STAGES.indexOf(j.stage);
    return STAGES.map((s, i) => `<span class="chip ${i < idx || j.status === "done" ? "done" : ""} ${i === idx && j.status === "running" ? "on" : ""}">${s}</span>`).join("<span class='arrow'>›</span>");
  }
  function jobHtml(j) {
    const plat = { youtube: "YouTube", twitch: "Twitch", kick: "Kick" }[j.platform] || j.platform;
    const running = ["queued", "running", "watching"].includes(j.status);
    return `
      <div class="job-head">
        <span class="badge ${j.is_live ? "live" : ""}">${plat} · ${j.is_live ? "LIVE" : "VOD"}</span>
        <a class="job-title" href="/jobs/${j.id}">${CS.esc(j.title || j.url)}</a>
        <span class="status s-${j.status}">${j.status}</span>
      </div>
      <div class="stages">${stageChips(j)}</div>
      <div class="bar"><div style="width:${j.progress || 0}%"></div></div>
      <div class="job-foot">
        <span class="muted small">${Math.round(j.progress || 0)}% · ${elapsed(j)} ${j.clip_count ? "· " + j.clip_count + " clips" : ""} ${j.ai_cost ? "· AI $" + j.ai_cost.toFixed(3) : ""}</span>
        ${j.error ? `<span class="err small">${CS.esc(j.error)}</span>` : ""}
        <span class="spacer"></span>
        ${j.clip_count ? `<a class="btn small" href="/review?job=${j.id}">Review clips</a>` : ""}
        <button class="small" data-act="log">Log</button>
        ${j.is_live && running ? `<button class="small" data-act="stop">Stop watching</button>` : ""}
        ${running ? `<button class="small danger" data-act="cancel">Cancel</button>` : `<button class="small" data-act="retry">Re-run</button><button class="small ghost" data-act="delete">✕</button>`}
      </div>
      <pre class="log ${openLogs.has(j.id) ? "" : "hidden"}"></pre>`;
  }
  function upsert(j) {
    const prev = jobs.get(j.id) || {};
    j = Object.assign(prev, j);
    jobs.set(j.id, j);
    let el = document.querySelector(`.job[data-id="${j.id}"]`);
    const list = $("jobs");
    if (!el) {
      list.querySelector("p.muted")?.remove();
      el = document.createElement("div");
      el.className = "job card";
      el.dataset.id = j.id;
      const after = [...list.children].find((c) => Number(c.dataset.id) < j.id);
      list.insertBefore(el, after || null);
    }
    const logText = el.querySelector(".log")?.textContent || "";
    el.innerHTML = jobHtml(j);
    el.querySelector(".log").textContent = logText;
  }
  $("jobs").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const el = btn.closest(".job"), id = Number(el.dataset.id), act = btn.dataset.act;
    try {
      if (act === "log") {
        const pre = el.querySelector(".log");
        pre.classList.toggle("hidden");
        if (pre.classList.contains("hidden")) openLogs.delete(id);
        else { openLogs.add(id); pre.textContent = await (await fetch(`/api/jobs/${id}/log`)).text(); pre.scrollTop = 1e9; }
      } else if (act === "delete") {
        if (!confirm("Remove this job from the list? (Its clips stay.)")) return;
        await CS.api("DELETE", `/api/jobs/${id}`);
        el.remove(); jobs.delete(id);
      } else {
        await CS.api("POST", `/api/jobs/${id}/${act}`);
      }
    } catch (err) { CS.toast(err.message, "error"); }
  });

  CS.on("job", upsert);
  CS.on("job_deleted", (d) => document.querySelector(`.job[data-id="${d.id}"]`)?.remove());
  CS.on("log", (d) => {
    if (!openLogs.has(d.job_id)) return;
    const pre = document.querySelector(`.job[data-id="${d.job_id}"] .log`);
    if (pre) { pre.textContent += (pre.textContent ? "\n" : "") + d.line; pre.scrollTop = 1e9; }
  });
  CS.on("clip", (c) => { const j = jobs.get(c.job_id); if (j && c._new) { j.clip_count = (j.clip_count || 0) + 1; upsert(j); } });

  async function load() {
    const d = await CS.api("GET", "/api/jobs");
    d.jobs.slice().reverse().forEach(upsert);
  }
  load();
  setInterval(() => jobs.forEach((j) => { if (j.status === "running" || j.status === "watching") upsert(j); }), 1000);
})();
