/* Job page: progress, log tail and (for live jobs) the score-over-time chart. */
(function () {
  const id = window.JOB_ID;
  const $ = (x) => document.getElementById(x);
  const log = $("log");
  fetch(`/api/jobs/${id}/log`).then((r) => r.text()).then((t) => { log.textContent = t; log.scrollTop = 1e9; });
  CS.on("log", (d) => { if (d.job_id === id) { log.textContent += "\n" + d.line; log.scrollTop = 1e9; } });
  CS.on("job", (j) => {
    if (j.id !== id) return;
    $("j-title").textContent = j.title || j.url;
    $("j-status").textContent = j.status; $("j-status").className = "status s-" + j.status;
    $("j-stage").textContent = j.stage; $("j-progress").textContent = Math.round(j.progress || 0);
    $("j-bar").style.width = (j.progress || 0) + "%";
    $("j-error").textContent = j.error || "";
    $("j-tokens").textContent = `${j.ai_input_tokens} in / ${j.ai_output_tokens} out`;
    $("j-cost").textContent = (j.ai_cost || 0).toFixed(3);
  });
  $("cancel")?.addEventListener("click", () => CS.api("POST", `/api/jobs/${id}/cancel`).catch((e) => CS.toast(e.message, "error")));
  $("stop")?.addEventListener("click", () => CS.api("POST", `/api/jobs/${id}/stop`).then(() => CS.toast("Stopping after the current step…")).catch((e) => CS.toast(e.message, "error")));

  const canvas = $("chart");
  if (!canvas) return;
  let data = { t: [], s: [], clips: [], threshold: 2 };
  function draw() {
    const ctx = canvas.getContext("2d");
    const W = (canvas.width = canvas.clientWidth * devicePixelRatio), H = (canvas.height = canvas.clientHeight * devicePixelRatio);
    ctx.clearRect(0, 0, W, H);
    if (!data.t.length) { ctx.fillStyle = "#8b92a6"; ctx.font = `${13 * devicePixelRatio}px system-ui`; ctx.fillText("Waiting for the first minute of audio…", 16, 30); return; }
    const t0 = data.t[0], t1 = data.t[data.t.length - 1] || t0 + 1;
    const smax = Math.max(data.threshold * 1.4, ...data.s), smin = Math.min(-1, ...data.s);
    const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (W - 20) + 10;
    const Y = (s) => H - 14 - ((s - smin) / (smax - smin)) * (H - 28);
    ctx.strokeStyle = "#ffb020"; ctx.setLineDash([6, 6]); ctx.beginPath(); ctx.moveTo(0, Y(data.threshold)); ctx.lineTo(W, Y(data.threshold)); ctx.stroke(); ctx.setLineDash([]);
    ctx.strokeStyle = "#7c5cff"; ctx.lineWidth = 1.5 * devicePixelRatio; ctx.beginPath();
    data.t.forEach((t, i) => (i ? ctx.lineTo(X(t), Y(data.s[i])) : ctx.moveTo(X(t), Y(data.s[i])))); ctx.stroke();
    ctx.fillStyle = "#ff3d6e";
    data.clips.forEach((c) => { if (c >= t0) { ctx.beginPath(); ctx.arc(X(c), 10 * devicePixelRatio, 5 * devicePixelRatio, 0, 7); ctx.fill(); ctx.fillRect(X(c) - 1, 10, 2, H); } });
    ctx.fillStyle = "#8b92a6"; ctx.font = `${11 * devicePixelRatio}px system-ui`;
    ctx.fillText(CS.fmtDur(t0), 10, H - 2); const lbl = CS.fmtDur(t1); ctx.fillText(lbl, W - ctx.measureText(lbl).width - 10, H - 2);
  }
  fetch(`/api/jobs/${id}/live-scores`).then((r) => r.json()).then((d) => { data = d; draw(); });
  CS.on("live_score", (d) => { if (d.job_id === id) { data = d; draw(); } });
  window.addEventListener("resize", draw);
})();
