/* Assignment board: accounts as columns grouped by platform; drag (or tap) clips onto accounts. */
(function () {
  const $ = (id) => document.getElementById(id);
  let pool = "approved";
  let data = { accounts: [], pool: [], assignments: [] };
  let selected = null;              // tap-to-assign: the clip waiting for an account
  try { pool = localStorage.getItem("board.pool") || "approved"; } catch (e) { /* storage blocked */ }
  document.querySelectorAll("#pool-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.pool === pool));

  async function load() {
    const q = new URLSearchParams({ pool });
    if ($("f-streamer").value) q.set("streamer_id", $("f-streamer").value);
    data = await CS.api("GET", "/api/board?" + q);
    render();
  }

  function render() {
    const nPlatforms = Object.keys(CS.PLATFORMS).filter((p) => data.accounts.some((a) => a.platform === p));
    let clips = data.pool;
    if ($("f-free").checked) clips = clips.filter((c) => !nPlatforms.every((p) => c.platforms.includes(p)));
    $("pool-count").textContent = `${clips.length} shown`;
    $("pool").innerHTML = clips.map((c) => `
      <div class="chip-clip ${selected === c.id ? "sel" : ""}" draggable="true" data-clip="${c.id}" title="${CS.esc(c.title)}">
        ${c.thumb_url ? `<img src="${CS.esc(c.thumb_url)}" alt="" loading="lazy" draggable="false">` : `<div class="noimg"></div>`}
        <div class="cc-body"><div class="cc-title">${CS.esc(c.title || "Clip #" + c.id)}</div>
          <div class="muted small">${CS.esc(c.streamer || "")} · ${CS.fmtDur(c.length)}${c.ready ? " · ☑" : ""}</div>
          <div class="cc-plats">${c.platforms.map((p) => `<span class="plat-dot" title="On ${CS.PLATFORMS[p]}">${CS.PICONS[p]}</span>`).join("")}</div>
        </div></div>`).join("") || `<p class="muted small" style="padding:8px">No clips here. Approve clips on the <a href="/review">Review</a> page.</p>`;

    $("no-accounts").classList.toggle("hidden", data.accounts.length > 0);
    const byAcc = {};
    data.assignments.forEach((a) => (byAcc[a.account_id] = byAcc[a.account_id] || []).push(a));
    $("board").innerHTML = Object.entries(CS.PLATFORMS).map(([p, label]) => {
      const accs = data.accounts.filter((a) => a.platform === p);
      if (!accs.length) return "";
      return `<section class="plat-section"><h2>${CS.PICONS[p]} ${label}</h2><div class="cols">${accs.map((a) => {
        const items = byAcc[a.id] || [];
        return `<div class="col drop" data-acc="${a.id}" style="--c:${CS.esc(a.color)}">
          <div class="col-head"><div class="row" style="justify-content:space-between">${CS.acctBadge(a)}<button class="small ghost" data-edit="${a.id}" title="Edit account">✎</button></div>
            <div class="muted small">${CS.esc(a.niche || "no niche set")} · ${CS.fmtNum(a.followers)} followers · ${items.length} clips</div></div>
          <div class="col-body">${items.map(mini).join("") || `<div class="drop-hint">Drop clips here</div>`}</div></div>`;
      }).join("")}</div></section>`;
    }).join("");
    $("sel-hint").classList.toggle("hidden", !selected);
    document.body.classList.toggle("selecting", !!selected);
  }

  function mini(a) {
    const c = a.clip || {};
    return `<div class="mini" data-id="${a.id}">
      ${c.thumb_url ? `<img src="${CS.esc(c.thumb_url)}" alt="" loading="lazy">` : ""}
      <div class="mini-body"><div class="mini-title">${CS.esc(c.title || "Clip #" + c.id)}</div>
        <div class="small"><span class="st st-${a.status}">${CS.STATUSES[a.status]}</span>${a.scheduled_at && a.status === "scheduled" ? ` · ${CS.esc(a.scheduled_at.slice(5))}` : ""}
        ${a.warnings.length ? `<span class="warn-ico" title="${CS.esc(a.warnings.join("\n"))}">⚠ ${a.warnings.length}</span>` : ""}</div></div>
      <button class="small ghost x" data-unassign="${a.id}" title="Remove">✕</button></div>`;
  }

  async function assign(clipId, accId) {
    try {
      const r = await CS.api("POST", "/api/assignments", { clip_id: Number(clipId), account_id: Number(accId) });
      const acc = data.accounts.find((a) => a.id === Number(accId));
      CS.toast(`Assigned to ${acc ? acc.handle : "account"}`, "ok", 2500);
      CS.showWarnings(r.warnings);
    } catch (e) { CS.toast(e.message, "error", 10000); }
    selected = null;
    load();
  }

  // ---- drag & drop (mouse)
  document.addEventListener("dragstart", (e) => {
    const el = e.target.closest(".chip-clip"); if (!el) return;
    e.dataTransfer.setData("text/plain", el.dataset.clip);
    e.dataTransfer.effectAllowed = "copy";
    document.body.classList.add("dragging");
  });
  document.addEventListener("dragend", () => document.body.classList.remove("dragging"));
  $("board").addEventListener("dragover", (e) => { const col = e.target.closest(".drop"); if (col) { e.preventDefault(); col.classList.add("over"); } });
  $("board").addEventListener("dragleave", (e) => { const col = e.target.closest(".drop"); if (col && !col.contains(e.relatedTarget)) col.classList.remove("over"); });
  $("board").addEventListener("drop", (e) => {
    const col = e.target.closest(".drop"); if (!col) return;
    e.preventDefault(); col.classList.remove("over");
    const clip = e.dataTransfer.getData("text/plain");
    if (clip) assign(clip, col.dataset.acc);
  });

  // ---- tap to assign (phones) + remove buttons
  $("pool").addEventListener("click", (e) => {
    const el = e.target.closest(".chip-clip"); if (!el) return;
    selected = selected === Number(el.dataset.clip) ? null : Number(el.dataset.clip);
    render();
    if (selected) $("board").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("board").addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-edit]");
    if (ed) { e.stopPropagation(); openAccount(data.accounts.find((a) => a.id === Number(ed.dataset.edit))); return; }
    const x = e.target.closest("[data-unassign]");
    if (x) {
      e.stopPropagation();
      if (!confirm("Remove this clip from the account?")) return;
      await CS.api("DELETE", `/api/assignments/${x.dataset.unassign}`); load(); return;
    }
    const col = e.target.closest(".drop");
    if (col && selected) { assign(selected, col.dataset.acc); return; }
    const m = e.target.closest(".mini");
    if (m) location.href = `/pipeline?highlight=${m.dataset.id}`;
  });
  $("sel-cancel").onclick = () => { selected = null; render(); };

  // ---- add / edit / remove accounts (this replaced the old Accounts tab)
  const dlg = $("acc-dlg");
  let editing = null;
  function openAccount(acc) {
    editing = acc || null;
    $("acc-title").textContent = acc ? `Edit ${acc.handle}` : "Add account";
    dlg.querySelectorAll("[data-k]").forEach((i) => {
      if (acc) i.value = acc[i.dataset.k] ?? "";
      else if (i.dataset.k !== "daily_limit" && i.dataset.k !== "platform") i.value = i.type === "color" ? "#7c5cff" : "";
    });
    dlg.querySelector('[data-k="platform"]').disabled = !!acc;
    $("acc-remove").classList.toggle("hidden", !acc);
    dlg.showModal();
  }
  $("add-acc").onclick = () => openAccount(null);
  $("acc-cancel").onclick = () => dlg.close();
  $("acc-save").onclick = async () => {
    const body = {};
    dlg.querySelectorAll("[data-k]").forEach((i) => (body[i.dataset.k] = i.value));
    if (!editing) delete body.color;               // new accounts get the next palette color
    try {
      if (editing) { delete body.platform; await CS.api("PUT", `/api/accounts/${editing.id}`, body); }
      else await CS.api("POST", "/api/accounts", body);
      dlg.close(); CS.toast("Account saved", "ok", 2000); load();
    } catch (err) { CS.toast(err.message, "error"); }
  };
  $("acc-remove").onclick = async () => {
    if (!confirm(`Remove ${editing.handle}? Accounts with posted clips are hidden instead, so your analytics stay.`)) return;
    try { const r = await CS.api("DELETE", `/api/accounts/${editing.id}`); dlg.close(); CS.toast(r.archived ? "Account hidden (stats kept)" : "Account removed", "ok"); load(); }
    catch (err) { CS.toast(err.message, "error"); }
  };

  document.querySelectorAll("#pool-tabs button").forEach((b) => b.addEventListener("click", () => {
    pool = b.dataset.pool;
    try { localStorage.setItem("board.pool", pool); } catch (e) { /* ignore */ }
    document.querySelectorAll("#pool-tabs button").forEach((x) => x.classList.toggle("on", x === b));
    load();
  }));
  $("f-streamer").addEventListener("change", load);
  $("f-free").addEventListener("change", render);
  load();
})();
