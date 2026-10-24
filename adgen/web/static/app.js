const $ = (s) => document.querySelector(s);
const state = { briefId: null, scriptsFile: null, scriptSet: null, avatarId: null };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const offline = () => $("#offline").checked;
const show = (id) => $(id).classList.remove("hidden");

async function post(url, data) {
  const body = data instanceof FormData ? data : Object.entries(data).reduce((f, [k, v]) => (f.append(k, v), f), new FormData());
  const r = await fetch(url, { method: "POST", body });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

async function waitJob(id, onLog) {
  for (;;) {
    const r = await fetch(`/api/jobs/${id}`).then((r) => r.json());
    onLog && onLog(r.log);
    if (r.status === "done") return r.result;
    if (r.status === "error") throw new Error(r.error);
    await new Promise((res) => setTimeout(res, 1200));
  }
}

function costTable(c) {
  const rows = c.lines.map((l) => `<tr><td>${esc(l.stage)}</td><td>${esc(l.provider)}</td><td>${esc(l.detail)}</td><td>$${l.usd.toFixed(3)}</td></tr>`).join("");
  return `<table class="cost"><tr><th>stage</th><th>provider</th><th>detail</th><th>USD</th></tr>${rows}<tr><th colspan="3">Estimated total</th><th>$${c.total_usd.toFixed(2)}</th></tr></table>`;
}

// ------------------------------------------------------------------ step 1: brief + scripts
async function refreshScriptEstimate() {
  const c = await post("/api/scripts/estimate", { offline: offline() });
  $("#script-estimate").textContent = `Estimated script cost: $${c.total_usd.toFixed(2)}`;
}

$("#load-sample").addEventListener("click", async () => {
  const s = await fetch("/api/sample").then((r) => r.json());
  const f = $("#brief-form");
  for (const k of ["name", "description", "target_audience", "cta", "product_url", "language"]) f.elements[k].value = s[k] || "";
  f.elements.selling_points.value = s.selling_points.join("\n");
  f.elements.tone.value = s.tone;
  f.querySelectorAll('input[name="length"]').forEach((el) => (el.checked = el.value == s.length));
  f.querySelectorAll('input[name="ratio"]').forEach((el) => (el.checked = s.aspect_ratios.includes(el.value)));
  const toFiles = async (urls) => {
    const dt = new DataTransfer();
    for (const u of urls) {
      const b = await fetch(u).then((r) => r.blob());
      dt.items.add(new File([b], u.split("/").pop(), { type: b.type }));
    }
    return dt.files;
  };
  f.elements.images.files = await toFiles(s.image_urls);
  f.elements.logo.files = await toFiles([s.logo_url]);
});

$("#brief-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const btn = f.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const fd = new FormData(f);
    fd.delete("ratio");
    fd.append("aspect_ratios", [...f.querySelectorAll('input[name="ratio"]:checked')].map((x) => x.value).join(","));
    const { brief_id } = await post("/api/brief", fd);
    state.briefId = brief_id;
    $("#script-estimate").textContent = "Writing scripts...";
    const { job } = await post("/api/scripts", { brief_id, offline: offline() });
    const res = await waitJob(job);
    state.scriptsFile = res.scripts_file;
    state.scriptSet = res.script_set;
    $("#script-estimate").textContent = `Scripts ready (cost $${res.script_set.cost_usd.toFixed(3)})`;
    renderScripts();
    await loadAvatars();
    ["#step-scripts", "#step-avatar", "#step-render"].forEach(show);
    refreshRenderEstimate();
  } catch (err) {
    $("#script-estimate").innerHTML = `<span class="error">${esc(err.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
});

function renderScripts() {
  const html = state.scriptSet.variants.map((v) => {
    const words = v.segments.reduce((n, s) => n + s.text.split(/\s+/).length, 0);
    const segs = v.segments.map((s) => `<div class="seg"><span class="tag ${s.visual}">${esc(s.role)} · ${esc(s.visual)}</span>${esc(s.text)}</div>`).join("");
    return `<div class="variant"><h3><input type="checkbox" class="pick" value="${esc(v.variant)}" checked> Variant ${esc(v.variant)} <span class="muted">— ${esc(v.angle)}, ${words} words (~${(words / 2.5).toFixed(0)}s)</span></h3>${segs}<div class="seg"><span class="tag">end card</span>${esc(v.on_screen_cta)}</div></div>`;
  }).join("");
  $("#scripts").innerHTML = `<div class="variants">${html}</div>`;
  document.querySelectorAll(".pick").forEach((el) => el.addEventListener("change", refreshRenderEstimate));
}

// ------------------------------------------------------------------ step 3: avatars
async function loadAvatars() {
  const list = await fetch("/api/avatars").then((r) => r.json());
  const box = $("#avatars");
  if (!list.length) {
    box.innerHTML = '<p class="muted">No presenters yet &mdash; create one below.</p>';
    return;
  }
  box.innerHTML = list.map((a) => `<button type="button" class="avatar" data-id="${esc(a.id)}" title="${esc(a.setting)}"><img src="${esc(a.portrait)}?t=${Date.now()}" alt=""><div><b>${esc(a.name)}</b><br>${esc(a.look)}<br><span class="muted">${esc(a.voice_provider)} voice</span></div></button>`).join("");
  box.querySelectorAll(".avatar").forEach((el) =>
    el.addEventListener("click", () => {
      box.querySelectorAll(".avatar").forEach((x) => x.classList.remove("selected"));
      el.classList.add("selected");
      state.avatarId = el.dataset.id;
    })
  );
  const pre = state.avatarId && box.querySelector(`[data-id="${CSS.escape(state.avatarId)}"]`);
  (pre || box.querySelector(".avatar")).click();
}

$("#avatar-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  fd.append("offline", offline());
  const status = $("#avatar-status");
  status.textContent = "Generating...";
  try {
    const { job } = await post("/api/avatars", fd);
    const res = await waitJob(job);
    state.avatarId = res.avatar_id;
    status.textContent = `Created ${res.avatar_id} ($${res.cost.total_usd.toFixed(3)})`;
    await loadAvatars();
  } catch (err) {
    status.innerHTML = `<span class="error">${esc(err.message)}</span>`;
  }
});

// ------------------------------------------------------------------ step 4: render
const picked = () => [...document.querySelectorAll(".pick:checked")].map((x) => x.value).join(",");

async function refreshRenderEstimate() {
  if (!state.scriptsFile) return;
  if (!picked()) {
    $("#render-estimate").innerHTML = '<p class="muted">Select at least one variant.</p>';
    return;
  }
  const c = await post("/api/render/estimate", {
    brief_id: state.briefId, scripts_file: state.scriptsFile, variants: picked(),
    offline: offline(), lipsync: $("#lipsync").value, music: $("#music").checked,
  });
  $("#render-estimate").innerHTML = costTable(c);
}
["#lipsync", "#music", "#offline"].forEach((id) => $(id).addEventListener("change", () => { refreshRenderEstimate(); refreshScriptEstimate(); }));

$("#render-btn").addEventListener("click", async () => {
  if (!state.avatarId) return alert("Pick or create a presenter first.");
  if (!picked()) return alert("Select at least one script variant.");
  const btn = $("#render-btn");
  const log = $("#render-log");
  btn.disabled = true;
  log.classList.remove("hidden");
  log.textContent = "Starting...";
  try {
    const { job } = await post("/api/render", {
      brief_id: state.briefId, scripts_file: state.scriptsFile, variants: picked(), avatar_id: state.avatarId,
      offline: offline(), lipsync: $("#lipsync").value, captions: $("#captions").checked,
      ai_label: $("#ai_label").checked, music: $("#music").checked, music_prompt: $("#music_prompt").value,
    });
    const res = await waitJob(job, (lines) => { log.textContent = lines.join("\n"); log.scrollTop = log.scrollHeight; });
    showResults(res.ads);
  } catch (err) {
    log.textContent += `\nERROR: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

function showResults(ads) {
  show("#step-results");
  const html = ads.map((a) => {
    const vids = Object.entries(a.videos).map(([ratio, url]) => `<p><b>${esc(ratio)}</b></p><video controls preload="metadata" poster="${esc(a.posters[ratio])}" src="${esc(url)}"></video>`).join("");
    const links = Object.entries(a.videos).map(([ratio, url]) => `<a href="${esc(url)}" download>MP4 ${esc(ratio)}</a>`).join("");
    const warn = a.warnings.map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("");
    return `<div class="ad"><h3>Variant ${esc(a.variant)} · ${a.duration.toFixed(1)}s · $${a.cost.toFixed(3)}</h3>${warn}${vids}<div class="links">${links}<a href="${esc(a.script)}" target="_blank">script</a></div><p class="muted">${esc(a.folder)}</p></div>`;
  }).join("");
  $("#results").innerHTML = `<div class="ads">${html}</div>`;
  $("#step-results").scrollIntoView({ behavior: "smooth" });
}

refreshScriptEstimate();
