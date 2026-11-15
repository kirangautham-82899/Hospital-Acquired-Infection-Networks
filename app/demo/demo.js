/* MRSA ward map: animated, read-only view of the saved P30 results.
   All numbers come from window.DEMO_DATA (written by src/demo_data.py).
   Scenes: the story (three real people), the hospital as "10 people per
   ward", one ward network for contacts / superspreader / intervention, and
   a "how close was each guess" chart for the forecast. Motion is decoration. */
(() => {
  "use strict";
  const D = window.DEMO_DATA;
  if (!D) { document.body.innerHTML = "<p style='padding:40px'>demo_data.js missing: run <code>python -m src.demo_data</code> from the project root.</p>"; return; }

  const G = D.groups;
  const MODEL = D.model;
  const KOOP = "koopman_targeted_" + MODEL;
  const W = 1000, H = 640;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // ?speed=N fast-forwards the animations (for checking a whole sequence quickly); 1 by default
  const FAST = Math.min(20, Math.max(1, +new URLSearchParams(location.search).get("speed") || 1));

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const pct = (v, d = 0) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
  const fmt = (v, d = 0) => Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  function mulberry32(a) { return () => { a |= 0; a = a + 0x6d2b79f5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  const rand = mulberry32(42);
  const rr = (a, b) => a + rand() * (b - a);

  function hexToRgb(h) {
    h = h.trim();
    if (h.startsWith("rgb")) { const m = h.match(/[\d.]+/g).map(Number); return m.slice(0, 3); }
    h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const mix = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
  const rgb = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

  let T = {};
  function readTokens() {
    const cs = getComputedStyle(document.body);
    const names = ["bg", "surface", "surface-2", "ink", "muted", "line", "floor", "floor-tile", "corridor", "wall", "accent", "pos", "patient", "staff", "unk", "safe", "person", "cap", "skin1", "skin2", "skin3", "skin4", "hair"];
    names.forEach((n) => { T[n] = hexToRgb(cs.getPropertyValue("--" + n) || "#888"); });
  }

  // ---------- derived data ----------
  const weekOf = (w) => D.weeks[w];
  const prevAt = (w, g) => { const r = weekOf(w).groups[g]; return r ? r.p : null; };
  const overall = D.weeks.map((wk) => {
    let t = 0, p = 0; G.forEach((g) => { const r = wk.groups[g]; if (r) { t += r.tested; p += r.positive; } });
    return t ? p / t : null;
  });
  const meanPrev = {}; G.forEach((g) => {
    const v = D.weeks.map((wk) => wk.groups[g]).filter(Boolean);
    const t = v.reduce((s, r) => s + r.tested, 0), p = v.reduce((s, r) => s + r.positive, 0);
    meanPrev[g] = t ? p / t : 0;
  });
  const holdStart = Math.max(...D.calibration_weeks) + 1;
  const linkMax = Math.max(...D.contacts.links.map((l) => l.hours));

  // ---------- layouts (canvas is 1000 x 640 units) ----------
  // Hospital: six rooms on a corridor. Each room shows 10 people; the coral
  // share follows the real swab share (P3), and a one-at-a-time sequence plays
  // each week (see the sequence engine below).
  const ROOM = {};
  const cols = [24, 350, 676], RW = 300, RH = 240, CORR = 320;
  G.forEach((g, i) => {
    const top = i < 3, x = cols[i % 3], y = top ? 22 : 378;
    ROOM[g] = { g, x, y, w: RW, h: RH, top, door: { x: x + RW / 2, y: top ? y + RH : y }, fa: 1 };
  });
  const PER_ROOM = 10;
  const people = {};
  G.forEach((g) => {
    const r = ROOM[g], staffOnly = D.people[g].patients === 0;
    people[g] = [...Array(PER_ROOM).keys()].map((k) => {
      const col = k % 5, row = Math.floor(k / 5);
      const hx = r.x + 42 + col * 54, hy = r.y + 132 + row * 78;
      return {
        g, k, role: staffOnly || k % 4 === 3 ? "staff" : "patient", scale: 1.7,
        hx, hy, x: hx, y: hy, want: 0, c: 0, m: 0, u: 0, alpha: 1, burst: -1,
        phase: rr(0, 6.28), blink: rr(1, 5), dir: rand() < 0.5 ? -1 : 1, turnT: rr(2, 8),
        skin: "skin" + (1 + Math.floor(rand() * 4)), hairStyle: Math.floor(rand() * 3), moving: false,
      };
    });
  });
  // real weekly counts per ward (src/transitions.py)
  const TR = D.transitions || {};
  const trOf = (w, g) => (TR[String(w)] || {})[g] || null;
  const kOf = (w, g) => { const r = D.weeks[w] && D.weeks[w].groups[g]; return r ? Math.round(r.p * PER_ROOM) : null; };

  // Ward network: one circle per ward on a ring; used by Contacts, Superspreader, Intervention.
  const maxPeople = Math.max(...G.map((g) => D.people[g].patients + D.people[g].staff));
  const NODE = {};
  G.forEach((g, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / G.length;
    const n = D.people[g].patients + D.people[g].staff;
    NODE[g] = { g, x: 500 + 300 * Math.cos(a), y: 326 + 212 * Math.sin(a), r: 34 + 20 * Math.sqrt(n / maxPeople), glow: 0 };
  });
  const linkPoint = (l, t) => {
    const A = NODE[l.a], B = NODE[l.b];
    const cx = (A.x + B.x) / 2 * 0.72 + 500 * 0.28, cy = (A.y + B.y) / 2 * 0.72 + 326 * 0.28; // bow toward the centre
    return [(1 - t) * (1 - t) * A.x + 2 * (1 - t) * t * cx + t * t * B.x, (1 - t) * (1 - t) * A.y + 2 * (1 - t) * t * cy + t * t * B.y, cx, cy];
  };
  const dropMax = Math.max(...D.superspreader.wards.map((w) => w.drop));

  // ---------- state ----------
  const STORY = 5; // internal id of the story scene (shown first)
  // Set by the host page (src/app_data.py demo_html): open on one scene and leave navigation to the host.
  const LOCK = !!window.DEMO_LOCK;
  const S = {
    scene: STORY, pos: 0, week: 5, playing: false, playAcc: 0, hover: null,
    fcWard: "Menard 2", fcWeek: 13,
    k: 1, R: 0.5, strategy: KOOP,
  };

  function targetedWards() {
    if (S.scene !== 4) return [];
    const r = interRow(S.strategy);
    if (S.strategy === "whole_hospital") return G.slice();
    return r && r.targeted_wards ? r.targeted_wards.split(",") : [];
  }
  function interRow(strategy) {
    if (strategy === "none") return D.interventions.rows.find((r) => r.strategy === "none");
    return D.interventions.rows.find((r) => r.strategy === strategy && r.k === S.k && Math.abs(r.R - S.R) < 1e-9);
  }

  // ---------- canvas ----------
  const cv = $("stage"), ctx = cv.getContext("2d");
  let scale = 1, cssW = 0;
  function resize() {
    const wrap = $("canvasWrap"); cssW = wrap.clientWidth;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssW * H / W * dpr);
    cv.style.height = (cssW * H / W) + "px";
    scale = cv.width / W;
  }
  new ResizeObserver(resize).observe($("canvasWrap"));

  function roundRect(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  function drawShield(x, y) {
    ctx.save(); ctx.translate(x, y);
    ctx.beginPath(); ctx.moveTo(0, -13); ctx.lineTo(11, -8); ctx.lineTo(10, 3); ctx.quadraticCurveTo(7, 11, 0, 15); ctx.quadraticCurveTo(-7, 11, -10, 3); ctx.lineTo(-11, -8); ctx.closePath();
    ctx.fillStyle = rgb(T.safe); ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.moveTo(-5, 1); ctx.lineTo(-1, 5); ctx.lineTo(6, -4); ctx.stroke();
    ctx.restore();
  }

  function isLow(g) {
    const r = weekOf(S.week).groups[g];
    return r ? r.low_n : false;
  }

  // ======================================================================
  // Scene: The hospital, as "10 people per ward". Red = carries MRSA.
  // ======================================================================
  // ======================================================================
  // Hospital scene: one event at a time.
  //   1. a carrier walks along the corridor to another ward and meets someone,
  //      who picks up MRSA (route = the busiest real contact link to that ward)
  //   2. inside a ward, a carrier passes it to a roommate
  //   3. somewhere a carrier clears it
  //   4. summary with the week's real counts; rooms settle to the real share
  // Who infected whom is not in the data: walker and target are illustrative;
  // the weekly counts, the shares and the ward links are real.
  // ======================================================================
  const SEQ = { week: -1, events: [], i: -1, phase: "", t: 0, walker: null, target: null, path: null, seg: 0, caption: "" };
  const SPEED = 165;

  function setCarriers(g, k) {
    if (k == null) return;
    const ps = people[g], on = ps.filter((p) => p.want === 1);
    if (on.length > k) on.slice(k).forEach((p) => { p.want = 0; });
    else {
      const off = ps.filter((p) => p.want === 0).sort((a, b) => (a.role === "patient" ? 0 : 1) - (b.role === "patient" ? 0 : 1) || a.k - b.k);
      off.slice(0, k - on.length).forEach((p) => { p.want = 1; });
    }
  }
  const carriers = (g) => people[g].filter((p) => p.want === 1);
  const clean = (g) => people[g].filter((p) => p.want === 0);
  const pickStaffFirst = (arr) => arr.find((p) => p.role === "staff") || arr[0];
  const pickPatientFirst = (arr) => arr.find((p) => p.role === "patient") || arr[0];
  const linkHours = (a, b) => (D.contacts.links.find((l) => (l.a === a && l.b === b) || (l.a === b && l.b === a)) || { hours: 0 }).hours;

  function sourceFor(dst) {
    // the ward with a carrier that shares the most contact-hours with dst
    return D.contacts.links.filter((l) => l.a === dst || l.b === dst)
      .map((l) => (l.a === dst ? l.b : l.a)).sort((a, b) => linkHours(b, dst) - linkHours(a, dst))
      .find((g) => carriers(g).length > 0) || null;
  }

  function buildWeek(w) {
    G.forEach((g) => setCarriers(g, kOf(Math.max(0, w - 1), g) ?? kOf(w, g)));
    G.forEach((g) => people[g].forEach((p) => { p.x = p.hx; p.y = p.hy; p.m = 0; p.burst = -1; p.moving = false; }));
    const byNew = G.filter((g) => trOf(w, g) && trOf(w, g).new > 0).sort((a, b) => trOf(w, b).new - trOf(w, a).new);
    const byClr = G.filter((g) => trOf(w, g) && trOf(w, g).cleared > 0).sort((a, b) => trOf(w, b).cleared - trOf(w, a).cleared);
    const ev = [];
    const dst = byNew.find((g) => sourceFor(g) && clean(g).length);
    if (dst) ev.push({ type: "cross", src: sourceFor(dst), dst });
    const inside = byNew.find((g) => g !== dst && carriers(g).length && clean(g).length) || (dst && carriers(dst).length ? dst : null);
    if (inside) ev.push({ type: "inside", src: inside, dst: inside });
    if (byClr[0]) ev.push({ type: "clear", src: byClr[0] });
    ev.push({ type: "summary" });
    Object.assign(SEQ, { week: w, events: ev, i: -1 });
    nextEvent();
  }

  function setPhase(phase, caption) {
    SEQ.phase = phase; SEQ.t = 0;
    if (caption != null) { SEQ.caption = caption; const el = $("seqCaption"); if (el) { el.innerHTML = caption; el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); } }
    const st = $("seqStep"); if (st) st.textContent = `${Math.min(SEQ.i + 1, SEQ.events.length)} / ${SEQ.events.length}`;
  }

  function nextEvent() {
    SEQ.i += 1; SEQ.walker = SEQ.target = null;
    const e = SEQ.events[SEQ.i];
    if (!e) { if (S.playing) { S.week = (S.week + 1) % D.weeks.length; syncWeekUI(); } return; }
    if (e.type === "cross" || e.type === "inside") {
      let w = pickStaffFirst(carriers(e.src));
      // staff are the ones who move between wards: hand the carrier role to a staff member (same count)
      if (e.type === "cross" && w && w.role !== "staff") {
        const s2 = clean(e.src).find((p) => p.role === "staff");
        if (s2) { w.want = 0; w.c = 0; s2.want = 1; s2.c = 1; w = s2; }
      }
      const t = pickPatientFirst(clean(e.dst).filter((p) => p !== w));
      if (!w || !t) { nextEvent(); return; }
      SEQ.walker = w; SEQ.target = t;
      const side = t.hx < (ROOM[e.dst].x + RW / 2) ? 1 : -1, spot = { x: t.hx + side * 30, y: t.hy + 2 };
      if (e.type === "cross") {
        const A = ROOM[e.src], B = ROOM[e.dst], inA = A.top ? -18 : 18, inB = B.top ? -18 : 18, lane = CORR + (A.top ? -10 : 10);
        SEQ.path = [{ x: w.hx, y: w.hy }, { x: A.door.x, y: A.door.y + inA }, { x: A.door.x, y: lane }, { x: B.door.x, y: lane }, { x: B.door.x, y: B.door.y + inB }, spot];
        setPhase("focus", `<b>A carrier on ${e.src}</b> sets off.`);
      } else {
        SEQ.path = [{ x: w.hx, y: w.hy }, spot];
        setPhase("focus", `<b>Inside ${e.src}:</b> most contact never leaves the ward.`);
      }
      SEQ.seg = 0;
    } else if (e.type === "clear") {
      SEQ.target = carriers(e.src)[0] || null;
      if (!SEQ.target) { nextEvent(); return; }
      setPhase("focus", `<b>On ${e.src},</b> a carrier's next swab comes back negative…`);
    } else {
      const t = weekTotals(SEQ.week);
      setPhase("summary", `<b>Week ${SEQ.week} in the data:</b> <span class="c-pos">+${t.new} caught MRSA</span> and <span class="c-safe">−${t.cleared} cleared</span> across the hospital.`);
      G.forEach((g) => setCarriers(g, kOf(SEQ.week, g)));
    }
  }

  function walk(p, path, dt) {
    const tgt = path[SEQ.seg + 1];
    if (!tgt) return true;
    const dx = tgt.x - p.x, dy = tgt.y - p.y, d = Math.hypot(dx, dy), m = SPEED * dt;
    p.moving = true; p.dir = dx >= 0 ? 1 : -1; p.phase += dt * 11;
    if (d <= m) { p.x = tgt.x; p.y = tgt.y; SEQ.seg += 1; return SEQ.seg >= path.length - 1; }
    p.x += dx / d * m; p.y += dy / d * m; return false;
  }

  function updateSequence(dt, time) {
    if (SEQ.week !== S.week) buildWeek(S.week);
    const e = SEQ.events[SEQ.i];
    // people settle toward their wanted colour; a burst runs on new infections
    G.forEach((g) => people[g].forEach((p) => {
      p.c = lerp(p.c, p.want, reduceMotion ? 1 : clamp(dt * 3, 0, 1));
      if (!p.moving) p.phase += dt * 2;
      p.blink -= dt; if (p.blink < 0) p.blink = rr(2.5, 6);
    }));
    // spotlight: rooms in the current event stay bright
    G.forEach((g) => {
      const on = !e || e.type === "summary" || g === e.src || g === e.dst;
      ROOM[g].fa = lerp(ROOM[g].fa, on ? 1 : 0.32, clamp(dt * 4, 0, 1));
      people[g].forEach((p) => { p.alpha = p === SEQ.walker ? 1 : ROOM[g].fa; });
    });
    if (!S.playing || !e) return;
    SEQ.t += dt;
    const w = SEQ.walker, t = SEQ.target;
    switch (SEQ.phase) {
      case "focus":
        if (SEQ.t > 1.4) {
          if (e.type === "clear") { setPhase("clear", `<b>On ${e.src},</b> a carrier's next swab comes back negative: <span class="c-safe">cleared</span>.`); t.want = 0; }
          else setPhase("walk", e.type === "cross"
            ? `It walks to <b>${e.dst}</b>. These two wards share <b>${fmt(linkHours(e.src, e.dst))} contact-hours</b> over the study.`
            : `A carrier walks over to a ${t.role} in the same room.`);
        }
        break;
      case "walk":
        if (walk(w, SEQ.path, dt)) { w.moving = false; w.dir = t.hx > w.x ? 1 : -1; setPhase("contact", `Close contact with a <b>${t.role}</b> on ${e.dst}…`); }
        break;
      case "contact":
        if (SEQ.t > 1.8) { t.want = 1; t.burst = time; setPhase("infect", `…who <span class="c-pos">now carries MRSA</span> too.`); }
        break;
      case "infect":
        if (SEQ.t > 1.6) { SEQ.path = SEQ.path.slice().reverse(); SEQ.path[SEQ.path.length - 1] = { x: w.hx, y: w.hy }; SEQ.seg = 0; setPhase("return", null); }
        break;
      case "return":
        if (walk(w, SEQ.path, dt * 1.3)) { w.moving = false; w.x = w.hx; w.y = w.hy; nextEvent(); }
        break;
      case "clear":
        t.m = lerp(t.m, SEQ.t < 1.4 ? 1 : 0, clamp(dt * 3, 0, 1));
        if (SEQ.t > 2.4) { t.m = 0; nextEvent(); }
        break;
      case "summary":
        if (SEQ.t > 3.2) nextEvent();
        break;
    }
  }

  function tag(x, y, text, col) {
    ctx.font = "700 12px Geist, Inter, system-ui, sans-serif"; const w = ctx.measureText(text).width + 16;
    roundRect(x - w / 2, y - 11, w, 22, 11); ctx.fillStyle = rgb(col); ctx.fill();
    ctx.beginPath(); ctx.moveTo(x - 5, y + 10); ctx.lineTo(x + 5, y + 10); ctx.lineTo(x, y + 16); ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(text, x, y + 4);
  }

  function drawHospital(time, dt) {
    updateSequence(dt, time);
    const e = SEQ.events[SEQ.i];
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = rgb(T.wall, 0.6); ctx.setLineDash([10, 12]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(20, CORR); ctx.lineTo(W - 20, CORR); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = rgb(T.muted, 0.8); ctx.font = "600 11px Geist, Inter, system-ui, sans-serif"; ctx.textAlign = "left"; ctx.fillText("CORRIDOR", 28, CORR - 10);
    G.forEach((g) => {
      const r = ROOM[g], row = weekOf(S.week).groups[g], focus = e && (g === e.src || g === e.dst) && e.type !== "summary";
      ctx.save(); ctx.globalAlpha = r.fa;
      ctx.save(); ctx.shadowColor = "rgba(40,30,70,0.12)"; ctx.shadowBlur = 18; ctx.shadowOffsetY = 6;
      roundRect(r.x, r.y, r.w, r.h, 18); ctx.fillStyle = rgb(T.floor); ctx.fill(); ctx.restore();
      roundRect(r.x, r.y, r.w, r.h, 18); ctx.lineWidth = focus ? 2.5 : 1.5; ctx.strokeStyle = focus ? rgb(T.accent) : rgb(T.wall); ctx.stroke();
      ctx.fillStyle = rgb(T.corridor); ctx.fillRect(r.door.x - 24, r.door.y - 3, 48, 6); // doorway
      ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "650 18px Geist, Inter, system-ui, sans-serif"; ctx.fillText(g, r.x + 20, r.y + 34);
      ctx.fillStyle = rgb(T.muted); ctx.font = "500 12px Geist, Inter, system-ui, sans-serif";
      ctx.fillText(row ? `${row.tested} swabbed this week · ${pct(row.p)} carry MRSA` : "nobody swabbed this week", r.x + 20, r.y + 54);
      ctx.restore();
    });
    // contact ring
    if (SEQ.walker && SEQ.target && (SEQ.phase === "contact" || SEQ.phase === "infect")) {
      const a = SEQ.walker, b = SEQ.target, cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2 - 24;
      ctx.beginPath(); ctx.ellipse(cx, cy, 56, 44, 0, 0, 7); ctx.fillStyle = rgb(T.accent, 0.08); ctx.fill();
      ctx.setLineDash([6, 6]); ctx.lineDashOffset = -time * 20; ctx.strokeStyle = rgb(T.accent, 0.85); ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
    }
    const all = G.flatMap((g) => people[g]).sort((a, b) => (a === SEQ.walker) - (b === SEQ.walker) || a.y - b.y);
    all.forEach((p) => {
      if (p.burst > 0 && time - p.burst < 1 && !reduceMotion) {
        const k = time - p.burst; ctx.beginPath(); ctx.arc(p.x, p.y - 22, 14 + k * 46, 0, 7); ctx.strokeStyle = rgb(T.pos, 0.7 * (1 - k)); ctx.lineWidth = 2.5; ctx.stroke();
      }
      drawFigure(p, time);
    });
    if (SEQ.walker && SEQ.phase !== "") tag(SEQ.walker.x, SEQ.walker.y - 62, "carrier", T.pos);
    if (SEQ.target && SEQ.phase === "infect") tag(SEQ.target.x, SEQ.target.y - 62, "new carrier", T.pos);
    if (SEQ.target && SEQ.phase === "clear") tag(SEQ.target.x, SEQ.target.y - 62, "cleared", T.safe);
    if (SEQ.phase === "summary") {
      ctx.save(); ctx.globalAlpha = Math.min(1, SEQ.t * 3);
      roundRect(330, CORR - 26, 340, 52, 26); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.strokeStyle = rgb(T.line); ctx.lineWidth = 1; ctx.stroke();
      const t = weekTotals(SEQ.week); ctx.textAlign = "center"; ctx.font = "700 17px Geist, Inter, system-ui, sans-serif";
      ctx.fillStyle = rgb(T.pos); ctx.fillText(`+${t.new} caught`, 440, CORR + 6); ctx.fillStyle = rgb(T.safe); ctx.fillText(`−${t.cleared} cleared`, 565, CORR + 6);
      ctx.restore();
    }
  }

  // ======================================================================
  // Scenes: Contacts / Superspreader / Intervention, as one ward network.
  // Circle = ward (size = people), ring = share of its contact time that
  // stays inside, line = contact between two wards (thicker = more hours).
  // ======================================================================
  function linkStyle(l) {
    const t = l.hours / linkMax, tw = targetedWards();
    let w = 1.5 + 11 * t, a = 0.16 + 0.5 * t, col = T.accent, flow = 0.5 + 2.5 * t;
    if (S.scene === 3) {
      const hot = l.a === topSpreadWard || l.b === topSpreadWard;
      col = hot ? T.pos : T.muted; a = hot ? 0.3 + 0.55 * t : 0.08 + 0.15 * t;
    }
    if (S.scene === 4 && S.strategy !== "whole_hospital" && (tw.includes(l.a) || tw.includes(l.b))) { w *= 1 - S.R; a *= 1 - S.R * 0.7; flow *= 1 - S.R; }
    if (S.scene === 4 && S.strategy === "whole_hospital") { w *= 1 - S.R / 3; flow *= 1 - S.R / 3; }
    if (S.hover && l.a !== S.hover && l.b !== S.hover) a *= 0.35;
    return { w, a, col, flow };
  }

  function drawNetwork(time) {
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    // soft centre glow
    const grd = ctx.createRadialGradient(500, 318, 20, 500, 318, 360);
    grd.addColorStop(0, rgb(T.accent, 0.08)); grd.addColorStop(1, rgb(T.accent, 0)); ctx.fillStyle = grd; ctx.fillRect(0, 0, W, H);

    const links = [...D.contacts.links].sort((a, b) => a.hours - b.hours);
    links.forEach((l) => {
      const st = linkStyle(l), [, , cx, cy] = linkPoint(l, 0), A = NODE[l.a], B = NODE[l.b];
      ctx.strokeStyle = rgb(st.col, st.a); ctx.lineWidth = Math.max(0.6, st.w); ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.quadraticCurveTo(cx, cy, B.x, B.y); ctx.stroke();
      // moving dots = contact flowing along the link
      if (!reduceMotion && st.flow > 0.05) {
        const n = Math.max(1, Math.round(st.flow));
        for (let k = 0; k < n; k++) {
          const t = (time * 0.12 * (0.6 + st.flow / 3) + k / n + l.hours * 0.001) % 1, [px, py] = linkPoint(l, t);
          ctx.fillStyle = rgb(st.col, Math.min(1, st.a + 0.35)); ctx.beginPath(); ctx.arc(px, py, 2.4 + st.w * 0.16, 0, 7); ctx.fill();
        }
      }
    });
    // centre caption: intervention result
    if (S.scene === 4) {
      const r = interRow(S.strategy);
      ctx.save(); ctx.shadowColor = "rgba(40,30,70,0.14)"; ctx.shadowBlur = 20; ctx.shadowOffsetY = 6;
      roundRect(400, 282, 200, 84, 18); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.restore();
      ctx.textAlign = "center"; ctx.fillStyle = rgb(T.safe); ctx.font = "700 40px Geist, Inter, system-ui, sans-serif";
      ctx.fillText(r ? "−" + fmt(r.drop_mean) : "—", 500, 326);
      ctx.fillStyle = rgb(T.muted); ctx.font = "500 13px Geist, Inter, system-ui, sans-serif"; ctx.fillText("MRSA-days over 16 weeks", 500, 350);
    }
    G.forEach((g) => drawNode(NODE[g], time));
  }

  function drawNode(n, time) {
    const g = n.g, tw = targetedWards(), sup = D.superspreader.wards.find((w) => w.ward === g);
    const dim = (S.hover && S.hover !== g) || (S.scene === 3 && g !== topSpreadWard && !S.hover) ? 0.55 : 1;
    ctx.save(); ctx.globalAlpha = dim;
    // superspreader: ripple from the #1 ward
    if (S.scene === 3 && g === topSpreadWard && !reduceMotion) {
      for (let i = 0; i < 3; i++) {
        const ph = (time * 0.4 + i / 3) % 1;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 10 + ph * 70, 0, 7); ctx.strokeStyle = rgb(T.pos, 0.4 * (1 - ph)); ctx.lineWidth = 2; ctx.stroke();
      }
    }
    // body
    ctx.save(); ctx.shadowColor = "rgba(40,30,70,0.16)"; ctx.shadowBlur = 20; ctx.shadowOffsetY = 6;
    ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 7); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.restore();
    if (S.scene === 3) { ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 7); ctx.fillStyle = rgb(T.pos, 0.08 + 0.32 * sup.drop / dropMax); ctx.fill(); }
    // ring: share of contact time spent inside the ward
    const rr2 = n.r + 7, shielded = S.scene === 4 && tw.includes(g) && S.strategy !== "whole_hospital";
    ctx.lineCap = "round"; ctx.lineWidth = 6;
    if (shielded) { ctx.beginPath(); ctx.arc(n.x, n.y, rr2, 0, 7); ctx.strokeStyle = rgb(T.safe); ctx.stroke(); }
    // contents
    ctx.textAlign = "center"; ctx.fillStyle = rgb(T.ink);
    if (S.scene === 3) {
      ctx.fillStyle = g === topSpreadWard ? rgb(T.pos) : rgb(T.ink); ctx.font = "700 20px Geist, Inter, system-ui, sans-serif"; ctx.fillText(fmt(sup.drop), n.x, n.y + 3);
      ctx.fillStyle = rgb(T.muted); ctx.font = "500 10.5px Geist, Inter, system-ui, sans-serif"; ctx.fillText("days saved", n.x, n.y + 18);
    } else {
      ctx.font = "700 18px Geist, Inter, system-ui, sans-serif"; ctx.fillText(pct(meanPrev[g]), n.x, n.y + 3);
      ctx.fillStyle = rgb(T.muted); ctx.font = "500 10.5px Geist, Inter, system-ui, sans-serif"; ctx.fillText("carry MRSA", n.x, n.y + 18);
    }
    // name under the circle
    const below = n.y > 318 || Math.abs(n.y - 318) < 40;
    const ny = n.y + (n.y < 200 ? -(n.r + 20) : n.r + 30);
    ctx.fillStyle = rgb(T.ink); ctx.font = "650 15px Geist, Inter, system-ui, sans-serif"; ctx.fillText(g, n.x, ny);
    if (S.scene === 3 && g === topSpreadWard) {
      ctx.font = "750 10.5px Geist, Inter, system-ui, sans-serif"; const label = "#1 SPREADER", bw = ctx.measureText(label).width + 16;
      const bx = n.x + n.r + 16; roundRect(bx, n.y - 10, bw, 20, 10); ctx.fillStyle = rgb(T.pos); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.fillText(label, bx + 8, n.y + 4);
    }
    if (S.scene === 4 && tw.includes(g) && S.strategy !== "whole_hospital") drawShield(n.x + n.r * 0.78, n.y - n.r * 0.78);
    ctx.restore();
    void below;
  }

  // ======================================================================
  // Contacts scene: one idea per step (all numbers from the P2 contact data).
  // ======================================================================
  const ws = (g) => D.contacts.within_share[g];
  const topLinks = [...D.contacts.links].sort((a, b) => b.hours - a.hours);
  const insideTotal = G.reduce((s, g) => s + D.contacts.inside_hours[g], 0);
  const insideShare = insideTotal / (insideTotal + 2 * D.contacts.links.reduce((s, l) => s + l.hours, 0));
  const mostInside = [...G].sort((a, b) => ws(b) - ws(a))[0];
  const leastInside = [...G].sort((a, b) => ws(a) - ws(b))[0];
  const bridgeLinks = D.contacts.links.filter((l) => l.a === leastInside || l.b === leastInside).sort((a, b) => b.hours - a.hours);
  const otherEnd = (l, g) => (l.a === g ? l.b : l.a);
  const CSTEPS = [
    { dur: 3.6, focus: G, rings: [], links: () => [], cap: `Six groups. Each circle is a ward; <b>bigger</b> means more people.` },
    { dur: 3.8, focus: [mostInside], rings: [mostInside], links: () => [], cap: `<b>${mostInside}</b> keeps <b>${pct(ws(mostInside))}</b> of its contact time inside the ward.` },
    { dur: 3.8, focus: [leastInside], rings: [mostInside, leastInside], links: () => [], cap: `The staff-only <b>${leastInside}</b> group keeps just <b>${pct(ws(leastInside))}</b>.` },
    { dur: 3.4, focus: G, rings: G, links: () => [], cap: `All the rings together: <b>most contact never leaves the ward</b>.` },
    ...topLinks.slice(0, 3).map((l, i) => ({
      dur: 5, focus: [l.a, l.b], rings: G, links: () => topLinks.slice(0, i + 1), walk: l,
      cap: `${["The busiest link", "The second busiest", "The third"][i]}: <b>${l.a} ↔ ${l.b}</b>, <b>${fmt(l.hours)} contact-hours</b> over the study.`,
    })),
    {
      dur: 5.4, focus: [leastInside, ...bridgeLinks.map((l) => otherEnd(l, leastInside))], rings: G, bridge: true,
      links: (t) => topLinks.slice(0, 3).concat(bridgeLinks.slice(0, Math.max(0, Math.floor((t - 0.4) / 0.55) + 1))),
      cap: `<b>${leastInside}</b> staff touch every ward: they are the <b>bridges</b> between wards.`,
    },
    { dur: 5.4, focus: G, rings: G, links: () => D.contacts.links, flow: true,
      cap: `<b>${Math.round(insideShare * 100)}%</b> of all contact stays inside a ward. MRSA can only cross along these lines.` },
  ];
  const CS = { i: 0, t: 0 };
  const walkerFig = { role: "staff", scale: 1.55, x: 0, y: 0, c: 0, m: 0, u: 0, alpha: 1, rank: 3, phase: 0, blink: 3, dir: 1, skin: "skin2", hairStyle: 0, moving: true };

  function csGo(i) {
    CS.i = (i + CSTEPS.length) % CSTEPS.length; CS.t = 0;
    const el = $("seqCaption"); if (el) { el.innerHTML = CSTEPS[CS.i].cap; el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); }
    const st = $("seqStep"); if (st) st.textContent = `${CS.i + 1} / ${CSTEPS.length}`;
  }
  function csReset() { CS.i = 0; CS.t = 0; G.forEach((g) => { NODE[g].ring = 0; NODE[g].fa = 0; }); D.contacts.links.forEach((l) => { l.vis = 0; }); }

  function drawContacts(time, dt) {
    const step = CSTEPS[CS.i];
    if (S.playing) { CS.t += dt; if (CS.t > step.dur) csGo(CS.i + 1); }
    const shown = new Set(step.links(CS.t).map((l) => l.a + "|" + l.b));
    const k = reduceMotion ? 1 : clamp(dt * 4, 0, 1);
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    const grd = ctx.createRadialGradient(500, 326, 20, 500, 326, 360);
    grd.addColorStop(0, rgb(T.accent, 0.07)); grd.addColorStop(1, rgb(T.accent, 0)); ctx.fillStyle = grd; ctx.fillRect(0, 0, W, H);

    // links: appear one by one; the current one is bold, earlier ones settle back
    [...D.contacts.links].sort((a, b) => a.hours - b.hours).forEach((l) => {
      l.vis = lerp(l.vis || 0, shown.has(l.a + "|" + l.b) ? 1 : 0, k);
      if (l.vis < 0.02) return;
      const cur = step.walk === l || (step.bridge && (l.a === leastInside || l.b === leastInside));
      const t = l.hours / linkMax, A = NODE[l.a], B = NODE[l.b], [, , cx, cy] = linkPoint(l, 0);
      let a = (0.18 + 0.5 * t) * l.vis * (cur ? 1.4 : 1);
      if (S.hover && l.a !== S.hover && l.b !== S.hover) a *= 0.3;
      ctx.strokeStyle = rgb(T.accent, Math.min(0.95, a)); ctx.lineWidth = (1.5 + 11 * t) * (cur ? 1.15 : 1); ctx.lineCap = "round";
      // the current link draws itself from A to B
      const p = step.walk === l ? clamp((CS.t - 0.3) / 1.2, 0, 1) : 1;
      ctx.beginPath(); ctx.moveTo(A.x, A.y);
      if (p >= 1) ctx.quadraticCurveTo(cx, cy, B.x, B.y);
      else for (let s = 1; s <= 24; s++) { const [x, y] = linkPoint(l, p * s / 24); ctx.lineTo(x, y); }
      ctx.stroke();
      if (step.flow && !reduceMotion) {
        const n = Math.max(1, Math.round(0.5 + 2.5 * t));
        for (let j = 0; j < n; j++) { const [px, py] = linkPoint(l, (time * 0.12 + j / n + l.hours * 0.001) % 1); ctx.fillStyle = rgb(T.accent, 0.8); ctx.beginPath(); ctx.arc(px, py, 2.4 + t * 2, 0, 7); ctx.fill(); }
      }
    });
    // hour labels for the busiest links once revealed (the current one counts up)
    topLinks.slice(0, 3).forEach((l) => {
      if ((l.vis || 0) < 0.5) return;
      const cur = step.walk === l, v = cur ? l.hours * clamp((CS.t - 0.3) / 2.2, 0, 1) : l.hours;
      const [mx, my] = linkPoint(l, 0.5), label = fmt(v) + " h";
      ctx.font = `${cur ? 700 : 600} ${cur ? 14 : 12}px Geist, Inter, system-ui, sans-serif`; const w = ctx.measureText(label).width + 16;
      roundRect(mx - w / 2, my - 12, w, 24, 12); ctx.fillStyle = cur ? rgb(T.accent) : rgb(T.surface); ctx.fill();
      ctx.strokeStyle = rgb(T.accent, 0.45); ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = cur ? "#fff" : rgb(T.ink); ctx.textAlign = "center"; ctx.fillText(label, mx, my + 4.5);
    });
    // one staff member walks the current link, A to B
    if (step.walk) {
      const p = clamp((CS.t - 0.6) / (step.dur - 1.6), 0, 1), [x, y] = linkPoint(step.walk, p), [x2] = linkPoint(step.walk, Math.min(1, p + 0.02));
      walkerFig.x = x; walkerFig.y = y + 10; walkerFig.dir = x2 >= x ? 1 : -1; walkerFig.moving = p > 0 && p < 1; walkerFig.phase += dt * 11;
      walkerFig.blink -= dt; if (walkerFig.blink < 0) walkerFig.blink = rr(2, 5);
    }
    // wards
    G.forEach((g) => {
      const n = NODE[g], focus = (step.focus.includes(g) && !S.hover) || S.hover === g;
      n.fa = lerp(n.fa == null ? 0 : n.fa, focus ? 1 : 0.4, k);
      n.ring = lerp(n.ring || 0, step.rings.includes(g) ? ws(g) : 0, reduceMotion ? 1 : clamp(dt * 2.2, 0, 1));
      ctx.save(); ctx.globalAlpha = n.fa;
      ctx.save(); ctx.shadowColor = "rgba(40,30,70,0.16)"; ctx.shadowBlur = 20; ctx.shadowOffsetY = 6;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 7); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.restore();
      const rr2 = n.r + 7; ctx.lineCap = "round"; ctx.lineWidth = 6;
      ctx.beginPath(); ctx.arc(n.x, n.y, rr2, 0, 7); ctx.strokeStyle = rgb(T.line); ctx.stroke();
      if (n.ring > 0.005) { ctx.beginPath(); ctx.arc(n.x, n.y, rr2, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * n.ring); ctx.strokeStyle = rgb(T.accent); ctx.stroke(); }
      ctx.textAlign = "center";
      if (step.rings.includes(g)) {
        ctx.fillStyle = rgb(T.ink); ctx.font = "700 20px Geist, Inter, system-ui, sans-serif"; ctx.fillText(pct(n.ring), n.x, n.y + 3);
        ctx.fillStyle = rgb(T.muted); ctx.font = "500 10.5px Geist, Inter, system-ui, sans-serif"; ctx.fillText("inside", n.x, n.y + 18);
      } else {
        const pp = D.people[g];
        ctx.fillStyle = rgb(T.ink); ctx.font = "700 20px Geist, Inter, system-ui, sans-serif"; ctx.fillText(pp.patients + pp.staff, n.x, n.y + 3);
        ctx.fillStyle = rgb(T.muted); ctx.font = "500 10.5px Geist, Inter, system-ui, sans-serif"; ctx.fillText("people", n.x, n.y + 18);
      }
      ctx.fillStyle = rgb(T.ink); ctx.font = "650 15px Geist, Inter, system-ui, sans-serif"; ctx.fillText(g, n.x, n.y + (n.y < 200 ? -(n.r + 20) : n.r + 30));
      ctx.restore();
    });
    if (step.walk) drawFigure(walkerFig, time);
  }

  // ======================================================================
  // Scene: Forecast, as "how close was each guess" for one week.
  // ======================================================================
  // ======================================================================
  // Forecast scene: each held-out week is built up in steps
  //   rows -> "same as last week" -> Koopman slides out -> real swabs drop in
  //   -> misses measured -> the week's score; after the last week, a verdict.
  // ======================================================================
  const FC = { x0: 210, x1: 800, y0: 136, dy: 70 };
  const fcMax = Math.ceil(Math.max(...D.forecast.points.flatMap((p) => [p.pred, p.actual]).filter((v) => v != null)) * 10 + 0.5) / 10;
  const fcX = (v) => FC.x0 + (FC.x1 - FC.x0) * clamp(v, 0, fcMax) / fcMax;
  const FC_WEEKS = [...new Set(D.forecast.points.map((p) => p.landing_week))].sort((a, b) => a - b);
  const rmseOf = (m) => (D.forecast.rmse.find((x) => x.model === m && x.h === 1) || {}).rmse;
  const FSTEPS = [
    { dur: 2.8, cap: (w) => `<b>Week ${w}.</b> Six wards. What share will carry MRSA?` },
    { dur: 3.6, cap: () => `The simplest guess: <b>same as last week</b>.` },
    { dur: 3.8, cap: () => `<b>Koopman's forecast</b>, made a week earlier, moves away from last week's value.` },
    { dur: 3.8, cap: () => `Then the <b>real swabs</b> come in.` },
    { dur: 4.0, cap: () => `Measure each <b>miss</b>: the distance from the real value to each guess.` },
    { dur: 4.0, cap: (w, s) => `Week ${w} score: Koopman missed by <b>${s.k} points</b> on average, "same as last week" by <b>${s.p}</b>.` },
  ];
  const VERDICT = { dur: 6, cap: () => `Over all ${FC_WEEKS.length} held-out weeks: <b>${(rmseOf(MODEL) * 100).toFixed(1)}</b> vs <b>${(rmseOf("persistence") * 100).toFixed(1)}</b> points (RMSE). <b>A tie</b>: Koopman does not beat the simplest guess.` };
  const FS = { wi: Math.max(0, FC_WEEKS.indexOf(13)), i: 0, t: 0 };
  const fsStep = () => (FS.i < FSTEPS.length ? FSTEPS[FS.i] : VERDICT);

  function fcRow(g, w) {
    const act = prevAt(w, g), k = fcPoint(MODEL, g, w), p = fcPoint("persistence", g, w);
    return act == null || !k ? null : { act, k: k.pred, p: p ? p.pred : act };
  }
  function weekScore(w) {
    let ek = 0, ep = 0, n = 0;
    G.forEach((g) => { const r = fcRow(g, w); if (r) { ek += Math.abs(r.k - r.act); ep += Math.abs(r.p - r.act); n++; } });
    return n ? { k: (ek / n * 100).toFixed(1), p: (ep / n * 100).toFixed(1) } : { k: "—", p: "—" };
  }
  function fsGo(wi, i) {
    const last = FS.i >= FSTEPS.length;
    if (i >= FSTEPS.length + (wi === FC_WEEKS.length - 1 ? 1 : 0)) { wi += 1; i = 0; }
    if (i < 0) { wi -= 1; i = FSTEPS.length - 1; }
    wi = (wi + FC_WEEKS.length) % FC_WEEKS.length;
    const weekChanged = FC_WEEKS[wi] !== S.fcWeek;
    Object.assign(FS, { wi, i, t: 0 }); S.fcWeek = FC_WEEKS[wi];
    const el = $("seqCaption"); if (el) { el.innerHTML = fsStep().cap(S.fcWeek, weekScore(S.fcWeek)); el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); }
    const st = $("seqStep"); if (st) st.textContent = FS.i < FSTEPS.length ? `${FS.i + 1} / ${FSTEPS.length}` : "verdict";
    document.querySelectorAll("[data-fw]").forEach((b) => b.classList.toggle("on", +b.dataset.fw === S.fcWeek));
    if (weekChanged || last) renderPanel(false);
  }

  function drawForecast(time, dt) {
    const step = fsStep();
    if (S.playing) { FS.t += dt; if (FS.t > step.dur) fsGo(FS.wi, FS.i + 1); }
    const t = FS.t, si = FS.i, ease = (x) => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
    const stagger = (i, d = 0.35, len = 0.5) => (si === FS.i ? clamp((t - 0.3 - i * d) / len, 0, 1) : 1);
    const w = S.fcWeek, verdict = FS.i >= FSTEPS.length;
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    ctx.save(); if (verdict) ctx.globalAlpha = 0.25;
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "650 22px Geist, Inter, system-ui, sans-serif"; ctx.fillText(`Week ${w}`, 40, 50);
    // legend appears with each layer
    const lg = [["Same as last week", T.muted, false, 1], [`Koopman (${MODEL})`, T.accent, true, 2], ["Real", T.pos, true, 3]];
    let lx = 140; ctx.font = "500 13px Geist, Inter, system-ui, sans-serif";
    lg.forEach(([label, c, solid, from]) => {
      if (si < from && !verdict) return;
      ctx.beginPath(); ctx.arc(lx + 6, 44, 6, 0, 7);
      if (solid) { ctx.fillStyle = rgb(c); ctx.fill(); } else { ctx.strokeStyle = rgb(c); ctx.lineWidth = 2.2; ctx.stroke(); }
      ctx.fillStyle = rgb(T.muted); ctx.fillText(label, lx + 18, 49); lx += ctx.measureText(label).width + 44;
    });
    // grid
    const yEnd = FC.y0 + FC.dy * (G.length - 1);
    for (let v = 0; v <= fcMax + 1e-9; v += 0.1) {
      const x = fcX(v); ctx.strokeStyle = rgb(T.line); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, FC.y0 - 30); ctx.lineTo(x, yEnd + 26); ctx.stroke();
      ctx.fillStyle = rgb(T.muted); ctx.textAlign = "center"; ctx.font = "500 12px Geist, Inter, system-ui, sans-serif";
      ctx.fillText(Math.round(v * 100) + "%", x, yEnd + 46);
    }
    ctx.fillStyle = rgb(T.muted); ctx.font = "600 11px Geist, Inter, system-ui, sans-serif"; ctx.textAlign = "left";
    if (si >= 4 || verdict) ctx.fillText("CLOSER GUESS", 836, FC.y0 - 34);
    G.forEach((g, i) => {
      const y = FC.y0 + i * FC.dy, r = fcRow(g, w), rowIn = si === 0 && !verdict ? ease(stagger(i, 0.12, 0.4)) : 1;
      ctx.save(); ctx.globalAlpha *= rowIn;
      if (g === S.fcWard || g === S.hover) { roundRect(24, y - 28, 952, 56, 12); ctx.fillStyle = rgb(T.accent, g === S.fcWard ? 0.09 : 0.05); ctx.fill(); }
      ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "600 15px Geist, Inter, system-ui, sans-serif"; ctx.fillText(g, 40, y + 5);
      if (!r) { ctx.fillStyle = rgb(T.muted); ctx.font = "500 13px Geist, Inter, system-ui, sans-serif"; ctx.fillText("not tested this week", FC.x0, y + 5); ctx.restore(); return; }
      const at = (from) => verdict || si > from ? 1 : si === from ? stagger(i) : 0;
      const pIn = at(1), kIn = at(2), aIn = at(3), mIn = at(4);
      // misses: lines grow from the real value toward each guess
      if (mIn > 0) {
        ctx.lineCap = "round";
        ctx.strokeStyle = rgb(T.muted, 0.5); ctx.lineWidth = 3; ctx.setLineDash([2, 6]);
        ctx.beginPath(); ctx.moveTo(fcX(r.act), y + 9); ctx.lineTo(lerp(fcX(r.act), fcX(r.p), ease(mIn)), y + 9); ctx.stroke(); ctx.setLineDash([]);
        ctx.strokeStyle = rgb(T.accent, 0.55); ctx.lineWidth = 4;
        ctx.beginPath(); ctx.moveTo(fcX(r.act), y - 9); ctx.lineTo(lerp(fcX(r.act), fcX(r.k), ease(mIn)), y - 9); ctx.stroke();
        if (mIn >= 1) {
          const dk = Math.abs(r.k - r.act), dp = Math.abs(r.p - r.act), tie = Math.abs(dk - dp) < 0.005;
          const label = tie ? "tie" : dk < dp ? "Koopman" : "last week", col = tie ? T.muted : dk < dp ? T.accent : T.ink;
          ctx.font = "650 12.5px Geist, Inter, system-ui, sans-serif"; const lw = ctx.measureText(label).width + 18;
          roundRect(836, y - 12, lw, 24, 12); ctx.fillStyle = rgb(col, 0.12); ctx.fill(); ctx.fillStyle = rgb(col); ctx.textAlign = "left"; ctx.fillText(label, 845, y + 4.5);
        }
      }
      // "same as last week" (hollow)
      if (pIn > 0) {
        ctx.globalAlpha *= ease(pIn); const sc = 0.6 + 0.4 * ease(pIn);
        ctx.beginPath(); ctx.arc(fcX(r.p), y + 9, 7 * sc, 0, 7); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.strokeStyle = rgb(T.muted); ctx.lineWidth = 2.4; ctx.stroke();
        ctx.globalAlpha /= ease(pIn) || 1;
      }
      // Koopman slides out from last week's value to its forecast
      if (kIn > 0) {
        const x = lerp(fcX(r.p), fcX(r.k), ease(kIn));
        ctx.beginPath(); ctx.arc(x, y - 9, 7.5, 0, 7); ctx.fillStyle = rgb(T.accent); ctx.fill();
        if (kIn < 1) { ctx.strokeStyle = rgb(T.accent, 0.35); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(fcX(r.p), y - 9); ctx.lineTo(x, y - 9); ctx.stroke(); }
      }
      // the real value drops in, with a ripple when it lands
      if (aIn > 0) {
        const yy = y - 46 * (1 - ease(aIn));
        ctx.beginPath(); ctx.arc(fcX(r.act), yy, 9.5, 0, 7); ctx.fillStyle = rgb(T.pos); ctx.fill(); ctx.strokeStyle = rgb(T.surface); ctx.lineWidth = 2.5; ctx.stroke();
        if (si === 3 && aIn >= 1 && !reduceMotion) {
          const k2 = clamp(t - 0.3 - i * 0.35 - 0.5, 0, 0.8) / 0.8;
          if (k2 < 1) { ctx.beginPath(); ctx.arc(fcX(r.act), y, 10 + k2 * 22, 0, 7); ctx.strokeStyle = rgb(T.pos, 0.5 * (1 - k2)); ctx.lineWidth = 2; ctx.stroke(); }
        }
      }
      ctx.restore();
    });
    // the week's score
    if (si >= 5 && !verdict) {
      const s = weekScore(w), a = ease(t / 0.5);
      ctx.save(); ctx.globalAlpha = a; ctx.textAlign = "left"; ctx.font = "600 15px Geist, Inter, system-ui, sans-serif";
      ctx.fillStyle = rgb(T.muted); ctx.fillText("Average miss this week:", 40, H - 22);
      ctx.fillStyle = rgb(T.accent); ctx.fillText(`Koopman ${s.k} pts`, 230, H - 22);
      ctx.fillStyle = rgb(T.ink); ctx.fillText(`same as last week ${s.p} pts`, 380, H - 22);
      ctx.restore();
    }
    ctx.restore();
    // verdict card over the dimmed chart
    if (verdict) {
      const a = ease(t / 0.6);
      ctx.save(); ctx.globalAlpha = a;
      ctx.shadowColor = "rgba(40,30,70,0.16)"; ctx.shadowBlur = 24; ctx.shadowOffsetY = 8;
      roundRect(230, 200, 540, 220, 22); ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.shadowColor = "transparent";
      ctx.textAlign = "center"; ctx.fillStyle = rgb(T.muted); ctx.font = "600 13px Geist, Inter, system-ui, sans-serif";
      ctx.fillText(`AVERAGE MISS OVER ${FC_WEEKS.length} HELD-OUT WEEKS (RMSE, POINTS)`, 500, 238);
      ctx.font = "750 56px Geist, Inter, system-ui, sans-serif"; ctx.fillStyle = rgb(T.accent); ctx.fillText((rmseOf(MODEL) * 100).toFixed(1), 380, 318);
      ctx.fillStyle = rgb(T.ink); ctx.fillText((rmseOf("persistence") * 100).toFixed(1), 620, 318);
      ctx.font = "500 14px Geist, Inter, system-ui, sans-serif"; ctx.fillStyle = rgb(T.muted);
      ctx.fillText("Koopman", 380, 346); ctx.fillText("same as last week", 620, 346);
      ctx.font = "700 18px Geist, Inter, system-ui, sans-serif"; ctx.fillStyle = rgb(T.ink); ctx.fillText("vs", 500, 306);
      ctx.font = "650 16px Geist, Inter, system-ui, sans-serif"; ctx.fillText("A tie: no clear win over the simplest guess.", 500, 392);
      ctx.restore();
    }
  }

  // which ward is under the pointer, in canvas units
  function hitWard(x, y) {
    if (S.scene === 0) return G.find((g) => { const r = ROOM[g]; return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }) || null;
    if (S.scene === 2) { const i = Math.round((y - FC.y0) / FC.dy); return i >= 0 && i < G.length && Math.abs(y - FC.y0 - i * FC.dy) < 30 ? G[i] : null; }
    return G.find((g) => Math.hypot(x - NODE[g].x, y - NODE[g].y) < NODE[g].r + 12) || null;
  }

  function drawGerm(x, y, r, time) {
    ctx.save(); ctx.translate(x, y); if (!reduceMotion) ctx.rotate(time * 0.8);
    ctx.strokeStyle = rgb(T.pos); ctx.lineWidth = 1.1; ctx.fillStyle = rgb(T.pos);
    for (let i = 0; i < 6; i++) { const a = i * Math.PI / 3; ctx.beginPath(); ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r); ctx.lineTo(Math.cos(a) * (r + 2.2), Math.sin(a) * (r + 2.2)); ctx.stroke(); ctx.beginPath(); ctx.arc(Math.cos(a) * (r + 2.6), Math.sin(a) * (r + 2.6), 0.9, 0, 7); ctx.fill(); }
    ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.fill();
    ctx.restore();
  }

  function drawFigure(f, time) {
    const moving = f.moving && !reduceMotion;
    const bob = moving ? Math.abs(Math.sin(f.phase)) * 1.8 : (reduceMotion ? 0 : Math.sin(f.phase) * 0.6);
    const x = f.x, y = f.y - bob, s = f.scale || 1.3;
    ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
    ctx.globalAlpha = lerp(1, 0.3, f.u) * (f.alpha == null ? 1 : f.alpha); // untested: faded ghost
    // shadow
    ctx.fillStyle = "rgba(0,0,0,0.13)"; ctx.beginPath(); ctx.ellipse(0, bob / s + 0.5, 7, 2.4, 0, 0, Math.PI * 2); ctx.fill();
    // MRSA halo + germ marker: the only red thing on the map
    if (f.c > 0.02) {
      const pr = reduceMotion ? 0 : Math.sin(time * 3 + f.rank) * 1.2;
      ctx.fillStyle = rgb(T.pos, 0.22 * f.c); ctx.beginPath(); ctx.arc(0, -13, 12.5 + pr, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = rgb(T.pos, 0.9 * f.c); ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(0, -13, 12.5 + pr, 0, Math.PI * 2); ctx.stroke();
      if (f.c > 0.5) drawGerm(8.5, -30 + (reduceMotion ? 0 : Math.sin(time * 2.2 + f.rank) * 1.2), 2.6, time);
    }
    let body = mix(T.person, T.pos, f.c);
    if (f.m) body = mix(body, T.safe, f.m); // mint while a carrier clears
    // legs
    const step = moving ? Math.sin(f.phase) * 2 : 0;
    ctx.strokeStyle = rgb(mix(body, [40, 40, 50], 0.35)); ctx.lineWidth = 2.2; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(-2.5, -3); ctx.lineTo(-2.5 + step * 0.5, 0); ctx.moveTo(2.5, -3); ctx.lineTo(2.5 - step * 0.5, 0); ctx.stroke();
    // body
    roundRect(-6.5, -15, 13, 13, 5.5); ctx.fillStyle = rgb(body); ctx.fill();
    if (f.role === "staff") { ctx.fillStyle = "rgba(255,255,255,0.55)"; ctx.fillRect(-1, -14, 2, 7); } // scrubs v-neck
    // head
    ctx.fillStyle = rgb(T[f.skin]); ctx.beginPath(); ctx.arc(0, -21, 6.2, 0, Math.PI * 2); ctx.fill();
    if (f.role === "staff") {
      ctx.fillStyle = rgb(T.cap); ctx.beginPath(); ctx.arc(0, -22.5, 6.4, Math.PI * 1.02, Math.PI * 1.98); ctx.fill();
    } else {
      ctx.fillStyle = rgb(T.hair); ctx.beginPath();
      if (f.hairStyle === 0) ctx.arc(0, -22, 6.3, Math.PI * 1.05, Math.PI * 1.95);
      else if (f.hairStyle === 1) { ctx.arc(-1, -22.5, 5.8, Math.PI, Math.PI * 1.9); }
      else ctx.ellipse(0, -26.2, 4.2, 2, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    // eyes (look the way they walk) and blink
    const dx = f.dir * 1.1;
    ctx.fillStyle = "#2a2622";
    if (f.blink < 0.12) { ctx.fillRect(-2.6 + dx, -21, 1.8, 0.7); ctx.fillRect(1.0 + dx, -21, 1.8, 0.7); }
    else { ctx.beginPath(); ctx.arc(-1.7 + dx, -20.8, 0.95, 0, 7); ctx.arc(1.9 + dx, -20.8, 0.95, 0, 7); ctx.fill(); }
    // little smile; a flatter mouth when colonised
    ctx.strokeStyle = "rgba(60,40,30,0.7)"; ctx.lineWidth = 0.8; ctx.beginPath();
    if (f.c > 0.5) { ctx.moveTo(-1.3 + dx, -18); ctx.lineTo(1.5 + dx, -18); } else ctx.arc(dx * 0.6, -18.8, 1.6, 0.2 * Math.PI, 0.8 * Math.PI);
    ctx.stroke();
    ctx.restore();
  }

  // ======================================================================
  // Story scene: ONE real (anonymised) chain, told one step at a time.
  // ======================================================================
  const ST = D.story;
  const DAY = 86400000;
  const toDay = (s) => Date.parse(s + "T00:00:00Z") / DAY;
  const fmtD = (d, y) => new Date(Math.round(d) * DAY).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: y ? "numeric" : undefined, timeZone: "UTC" });
  const dates = (arr) => arr.map((e) => fmtD(toDay(e.date))).join(", ");
  const swabs = (w) => ST.events.filter((e) => e.who === w && e.event === "swab");
  const touches = (t) => ST.events.filter((e) => e.who === t && e.event === "contact");
  const minutes = (arr) => arr.reduce((s, e) => s + e.minutes, 0);
  const nDays = (arr) => new Set(arr.map((e) => e.date)).size;
  const A_sw = swabs("A"), B_sw = swabs("B"), C_sw = swabs("C"), AB = touches("AB"), BC = touches("BC");
  const A_before = A_sw.filter((e) => e.date <= AB[0].date);
  const B_pos1 = B_sw.find((e) => e.mrsa === 1);
  const B_neg = B_sw.filter((e) => e.mrsa === 0 && e.date < B_pos1.date);
  const B_carry = B_sw.filter((e) => e.date > B_pos1.date && e.date < BC[0].date);
  const C_pos1 = C_sw.find((e) => e.mrsa === 1);
  const C_neg = C_sw.filter((e) => e.mrsa === 0 && e.date < C_pos1.date);
  const C_after = C_sw.filter((e) => e.date > C_pos1.date);
  const oneIn = Math.round(1 / (1 - Math.exp(-D.params.beta)));
  const t0 = toDay(ST.events[0].date) - 4, t1 = toDay(ST.events[ST.events.length - 1].date) + 4;

  const HOME = { A: { x: 230, y: 330 }, B: { x: 500, y: 290 }, C: { x: 770, y: 330 } };
  const near = (w, side) => ({ x: HOME[w].x + side * 130, y: HOME[w].y + 4 });
  const STEPS = [
    { title: "Meet Patient A.", date: A_before.at(-1).date, focus: ["A"], st: { A: 1 }, badge: { A: 1 }, B: "home",
      text: `A patient on ${ST.ward}. Every swab (${dates(A_before)}) found MRSA of strain type <b>${ST.strain}</b>. A is a <b>carrier</b>.` },
    { title: "Meet Staff member B.", date: B_neg.at(-1).date, focus: ["B"], st: { A: 1, B: 0 }, badge: { B: 0 }, B: "home",
      text: `B works on the same ward. B's swabs on ${dates(B_neg)} found <b>no MRSA</b>.` },
    { title: "B and A meet.", date: AB.at(-1).date, focus: ["A", "B"], st: { A: 1, B: 0 }, B: near("A", 1), contact: "AB",
      text: `The wearable sensors logged <b>${fmt(minutes(AB))} minutes</b> of close contact between them, over ${nDays(AB)} days (${dates(AB)}).` },
    { title: "B tests positive.", date: B_pos1.date, focus: ["B"], st: { A: 1, B: 1 }, badge: { B: 1 }, B: near("A", 1),
      text: `B's next swab, on ${fmtD(toDay(B_pos1.date))}, found MRSA of strain <b>${B_pos1.strain}</b>: the <b>same type</b> A carries.` },
    { title: "B stays a carrier.", date: B_carry.at(-1).date, focus: ["B"], st: { A: 1, B: 1 }, B: "home",
      text: `B's next ${B_carry.length} swabs, up to ${fmtD(toDay(B_carry.at(-1).date))}, were ${B_carry.every((e) => e.mrsa === 1) ? "all" : "mostly"} positive. Staff can carry MRSA for weeks without being ill.` },
    { title: "Meet Patient C.", date: C_neg.at(-1).date, focus: ["C"], st: { A: 1, B: 1, C: 0 }, badge: { C: 0 }, B: "home",
      text: `Another patient on ${ST.ward}. C's swab on ${dates(C_neg)} found <b>no MRSA</b>.` },
    { title: "B and C meet.", date: BC.at(-1).date, focus: ["B", "C"], st: { A: 1, B: 1, C: 0 }, B: near("C", -1), contact: "BC",
      text: `<b>${fmt(minutes(BC))} minutes</b> of close contact, over ${nDays(BC)} days (${dates(BC)}).` },
    { title: "C tests positive.", date: C_pos1.date, focus: ["C"], st: { A: 1, B: 1, C: 1 }, badge: { C: 1 }, B: near("C", -1),
      text: `C's next swab, on ${fmtD(toDay(C_pos1.date))}, found MRSA of strain <b>${C_pos1.strain}</b>, the same type again.` },
    { title: "C clears it.", date: C_after.at(-1).date, focus: ["C"], st: { A: 1, B: 1, C: 0 }, badge: { C: 0 }, B: "home",
      text: `C's swabs on ${dates(C_after)} were negative again. Carriage comes and goes. Our model calls this <b>S → I → S</b>: susceptible, then colonised, then susceptible again.` },
    { title: "One possible route, not proof.", date: C_after.at(-1).date, focus: null, st: { A: 1, B: 1, C: 0 }, B: "home", final: true,
      text: `The timing and the strain fit, but strain ${ST.strain} makes up <b>${pct(ST.strain_share)}</b> of all MRSA swabs, so B and C could have caught it elsewhere. Our SIS model applies this to every contact of all 589 people: each hour of contact passes MRSA about <b>1 time in ${fmt(oneIn)}</b>, so it's the thousands of contact-hours that drive spread.` },
  ];

  const storyPeople = ["A", "B", "C"].map((w, i) => ({
    who: w, role: w === "B" ? "staff" : "patient", x: HOME[w].x, y: HOME[w].y, tx: HOME[w].x, ty: HOME[w].y, scale: 3.1,
    c: 0, u: 0, alpha: 0, rank: i * 3, phase: i, blink: 2 + i, dir: w === "C" ? -1 : 1, skin: ["skin2", "skin1", "skin3"][i], hairStyle: [0, 0, 2][i], moving: false,
  }));
  const extras = [...Array(14).keys()].map((k) => {
    const left = k % 2 === 0, x = left ? rr(70, 160) : rr(840, 930), y = rr(150, 400);
    return { role: rand() < 0.6 ? "patient" : "staff", x: k < 7 ? x : rr(380, 620), y: k < 7 ? y : rr(370, 405), scale: 1.25, c: 0, u: 0, alpha: 0.2,
      rank: 20 + k, phase: rr(0, 6), blink: rr(1, 5), dir: 1, skin: "skin" + (1 + (k % 4)), hairStyle: k % 3, moving: false };
  });
  const SS = { step: 0, playing: true, acc: 0, since: 0, day: toDay(STEPS[0].date), count: 0 };
  const STEP_SECONDS = 6.5;

  function storyGo(i) {
    SS.step = (i + STEPS.length) % STEPS.length; SS.acc = 0; SS.since = 0; SS.count = 0;
    renderBar(); renderPanel(true);
  }

  function updateStory(dt) {
    const step = STEPS[SS.step];
    SS.since += dt;
    if (SS.playing) { SS.acc += dt; if (SS.acc > (step.final ? STEP_SECONDS * 1.6 : STEP_SECONDS)) storyGo(SS.step + 1); }
    SS.day = lerp(SS.day, toDay(step.date), reduceMotion ? 1 : clamp(dt * 2.5, 0, 1));
    storyPeople.forEach((p) => {
      const shown = p.who in step.st, foc = !step.focus || step.focus.includes(p.who);
      p.alpha = lerp(p.alpha, shown ? (foc ? 1 : 0.32) : 0, clamp(dt * 4, 0, 1));
      const wantC = shown ? step.st[p.who] : 0;
      const ready = !step.badge || !(p.who in step.badge) || SS.since > 0.9; // colour changes after the swab pops
      if (ready) p.c = lerp(p.c, wantC, reduceMotion ? 1 : clamp(dt * 3, 0, 1));
      if (p.who === "B") { const t = step.B === "home" ? HOME.B : step.B; p.tx = t.x; p.ty = t.y; }
      const dx = p.tx - p.x, dy = p.ty - p.y, d = Math.hypot(dx, dy);
      if (d > 1 && !reduceMotion) { const m = Math.min(d, 150 * dt); p.x += dx / d * m; p.y += dy / d * m; p.moving = true; p.dir = dx >= 0 ? 1 : -1; p.phase += dt * 9; }
      else { if (reduceMotion) { p.x = p.tx; p.y = p.ty; } p.moving = false; p.phase += dt * 2; }
      p.blink -= dt; if (p.blink < 0) p.blink = rr(2, 5);
      if (!p.moving && p.who !== "B") p.dir = p.who === "A" ? 1 : -1;
      if (!p.moving && p.who === "B" && step.B !== "home") p.dir = step.contact === "AB" || SS.step === 3 ? -1 : 1;
    });
    extras.forEach((e) => { e.phase += dt * 2; e.blink -= dt; if (e.blink < 0) e.blink = rr(2, 6); });
    if (step.contact) SS.count = lerp(SS.count, minutes(step.contact === "AB" ? AB : BC), clamp(dt * 1.6, 0, 1));
  }

  function pill(x, y, text, bg, fg, font) {
    ctx.font = font || "650 13px Geist, Inter, system-ui, sans-serif"; const w = ctx.measureText(text).width + 22;
    roundRect(x - w / 2, y - 13, w, 26, 13); ctx.fillStyle = bg; ctx.fill(); ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.fillText(text, x, y + 4.5);
    return w;
  }

  function drawSwabBubble(p, positive, t) {
    const k = reduceMotion ? 1 : clamp(t / 0.45, 0, 1), e = 1 - Math.pow(1 - k, 3), sc = 0.6 + 0.4 * e + (k < 1 ? 0 : 0);
    const x = p.x + 46, y = p.y - 132;
    ctx.save(); ctx.globalAlpha = e * p.alpha; ctx.translate(x, y); ctx.scale(sc, sc);
    roundRect(-62, -20, 124, 40, 20); ctx.fillStyle = positive ? rgb(T.pos) : rgb(T.surface); ctx.fill();
    ctx.strokeStyle = positive ? rgb(T.pos) : rgb(T.wall); ctx.lineWidth = 1.5; ctx.stroke();
    // little tail
    ctx.beginPath(); ctx.moveTo(-30, 18); ctx.lineTo(-42, 32); ctx.lineTo(-18, 19); ctx.closePath(); ctx.fillStyle = positive ? rgb(T.pos) : rgb(T.surface); ctx.fill();
    // test tube
    ctx.save(); ctx.translate(-40, 0); ctx.rotate(0.35);
    roundRect(-4, -12, 8, 24, 4); ctx.fillStyle = positive ? "rgba(255,255,255,0.9)" : rgb(T["surface-2"]); ctx.fill();
    ctx.strokeStyle = positive ? "#fff" : rgb(T.muted); ctx.lineWidth = 1.2; ctx.stroke();
    ctx.fillStyle = positive ? rgb(T.pos) : rgb(T.muted); ctx.fillRect(-3, 2, 6, 8); ctx.restore();
    ctx.fillStyle = positive ? "#fff" : rgb(T.ink); ctx.font = "750 14px Geist, Inter, system-ui, sans-serif"; ctx.textAlign = "left";
    ctx.fillText(positive ? "MRSA +" : "No MRSA", -24, 5);
    ctx.restore();
  }

  function drawStory(time) {
    const step = STEPS[SS.step];
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    // the ward
    const R = { x: 20, y: 18, w: 960, h: 410 };
    ctx.save(); ctx.shadowColor = "rgba(0,0,0,0.16)"; ctx.shadowBlur = 24; ctx.shadowOffsetY = 8;
    roundRect(R.x, R.y, R.w, R.h, 22); ctx.fillStyle = rgb(T.floor); ctx.fill(); ctx.restore();
    ctx.save(); roundRect(R.x, R.y, R.w, R.h, 22); ctx.clip();
    ctx.strokeStyle = rgb(T["floor-tile"]); ctx.lineWidth = 1;
    for (let x = R.x + 32; x < R.x + R.w; x += 32) { ctx.beginPath(); ctx.moveTo(x, R.y); ctx.lineTo(x, R.y + R.h); ctx.stroke(); }
    for (let y = R.y + 32; y < R.y + R.h; y += 32) { ctx.beginPath(); ctx.moveTo(R.x, y); ctx.lineTo(R.x + R.w, y); ctx.stroke(); }
    ctx.restore();
    roundRect(R.x, R.y, R.w, R.h, 22); ctx.strokeStyle = rgb(T.wall); ctx.lineWidth = 2; ctx.stroke();
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "750 20px Geist, Inter, system-ui, sans-serif"; ctx.fillText(ST.ward + " ward", R.x + 24, R.y + 38);
    pill(R.x + R.w - 92, R.y + 34, fmtD(SS.day, true), rgb(T.ink), rgb(T.surface), "700 14px Geist, Inter, system-ui, sans-serif");

    // contact: ring around the pair + minute counter + possible-route particles
    if (step.contact) {
      const [a, b] = step.contact === "AB" ? [storyPeople[0], storyPeople[1]] : [storyPeople[1], storyPeople[2]];
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2 - 40, k = clamp(SS.since / 0.8, 0, 1);
      ctx.save(); ctx.globalAlpha = k;
      ctx.beginPath(); ctx.ellipse(cx, cy, 160, 105, 0, 0, Math.PI * 2); ctx.fillStyle = rgb(T.accent, 0.08); ctx.fill();
      ctx.setLineDash([8, 7]); ctx.lineDashOffset = -time * 20; ctx.strokeStyle = rgb(T.accent, 0.8); ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
      pill(cx, cy - 118, `${fmt(SS.count)} min of contact`, rgb(T.accent), "#fff", "700 14px Geist, Inter, system-ui, sans-serif");
      ctx.restore();
      if (!reduceMotion && SS.since > 1) {
        const src = a, dst = b; // the carrier is the first of the pair: A in A-B, B in B-C
        for (let i = 0; i < 6; i++) {
          const t = ((time * 0.35 + i / 6) % 1), x = lerp(src.x, dst.x, t), y = lerp(src.y - 60, dst.y - 60, t) - Math.sin(t * Math.PI) * 30;
          ctx.fillStyle = rgb(T.pos, 0.75 * Math.sin(t * Math.PI)); ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill();
        }
      }
    }

    const all = extras.concat(storyPeople.filter((p) => p.alpha > 0.01)).sort((a, b) => a.y - b.y);
    all.forEach((f) => drawFigure(f, time));

    // name tags + swab bubbles
    storyPeople.forEach((p) => {
      if (p.alpha < 0.02) return;
      ctx.save(); ctx.globalAlpha = p.alpha;
      const name = (p.who === "B" ? "Staff " : "Patient ") + p.who;
      const status = p.c > 0.5 ? `carries MRSA ${ST.strain}` : "no MRSA";
      ctx.textAlign = "center"; ctx.fillStyle = rgb(T.ink); ctx.font = "750 17px Geist, Inter, system-ui, sans-serif"; ctx.fillText(name, p.x, p.y + 30);
      ctx.fillStyle = p.c > 0.5 ? rgb(T.pos) : rgb(T.muted); ctx.font = "600 13px Geist, Inter, system-ui, sans-serif"; ctx.fillText(status, p.x, p.y + 48);
      ctx.restore();
      if (step.badge && p.who in step.badge) drawSwabBubble(p, step.badge[p.who] === 1, SS.since - 0.3);
    });

    drawStoryTimeline();
  }

  function drawStoryTimeline() {
    const L = 120, Rr = 960, X = (d) => L + (Rr - L) * (d - t0) / (t1 - t0);
    const lanes = { A: 478, B: 522, C: 566 };
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.muted); ctx.font = "650 11px Geist, Inter, system-ui, sans-serif";
    ctx.fillText("SWABS AND CONTACTS OVER TIME", 24, 452);
    ["A", "B", "C"].forEach((w) => {
      const y = lanes[w];
      ctx.fillStyle = rgb(T.ink); ctx.font = "650 13px Geist, Inter, system-ui, sans-serif"; ctx.fillText((w === "B" ? "Staff " : "Patient ") + w, 24, y + 4);
      ctx.strokeStyle = rgb(T.line); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(Rr, y); ctx.stroke();
    });
    // month ticks
    ctx.fillStyle = rgb(T.muted); ctx.font = "500 11px Geist, Inter, system-ui, sans-serif"; ctx.textAlign = "center";
    for (let d = Math.ceil(t0); d <= t1; d++) {
      const dt = new Date(d * DAY);
      if (dt.getUTCDate() === 1 || dt.getUTCDate() === 15) { ctx.fillText(fmtD(d), X(d), 604); ctx.strokeStyle = rgb(T.line); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(X(d), 466); ctx.lineTo(X(d), 580); ctx.stroke(); }
    }
    const now = SS.day + 0.5;
    // contacts: blue bars between the two lanes, height by minutes
    ST.events.filter((e) => e.event === "contact").forEach((e) => {
      const d = toDay(e.date), x = X(d), [y1, y2] = e.who === "AB" ? [lanes.A, lanes.B] : [lanes.B, lanes.C];
      const on = d <= now, h = (y2 - y1 - 12) * clamp(0.35 + e.minutes / 90, 0, 1), ym = (y1 + y2) / 2;
      roundRect(x - 3, ym - h / 2, 6, h, 3); ctx.fillStyle = rgb(T.accent, on ? 0.9 : 0.18); ctx.fill();
    });
    // swabs: red dot = MRSA, open circle = no MRSA
    ST.events.filter((e) => e.event === "swab").forEach((e) => {
      const d = toDay(e.date), on = d <= now, x = X(d), y = lanes[e.who];
      ctx.beginPath(); ctx.arc(x, y, 6.5, 0, 7);
      if (e.mrsa === 1) { ctx.fillStyle = rgb(T.pos, on ? 1 : 0.22); ctx.fill(); }
      else { ctx.fillStyle = rgb(T.surface); ctx.fill(); ctx.strokeStyle = rgb(T.muted, on ? 1 : 0.3); ctx.lineWidth = 2; ctx.stroke(); }
    });
    // playhead
    const px = X(SS.day);
    ctx.strokeStyle = rgb(T.ink, 0.7); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(px, 462); ctx.lineTo(px, 584); ctx.stroke();
    ctx.fillStyle = rgb(T.ink); ctx.beginPath(); ctx.moveTo(px - 6, 458); ctx.lineTo(px + 6, 458); ctx.lineTo(px, 466); ctx.closePath(); ctx.fill();
    // key
    ctx.textAlign = "left"; ctx.font = "500 11.5px Geist, Inter, system-ui, sans-serif"; let kx = 420; const ky = 452;
    ctx.fillStyle = rgb(T.pos); ctx.beginPath(); ctx.arc(kx, ky - 4, 5, 0, 7); ctx.fill(); ctx.fillStyle = rgb(T.muted); ctx.fillText("swab: MRSA", kx + 10, ky); kx += 100;
    ctx.beginPath(); ctx.arc(kx, ky - 4, 5, 0, 7); ctx.strokeStyle = rgb(T.muted); ctx.lineWidth = 2; ctx.stroke(); ctx.fillText("swab: no MRSA", kx + 10, ky); kx += 115;
    roundRect(kx - 3, ky - 11, 6, 14, 3); ctx.fillStyle = rgb(T.accent); ctx.fill(); ctx.fillStyle = rgb(T.muted); ctx.fillText("contact day (taller = longer)", kx + 10, ky);
  }

  let last = performance.now(), clock = 0;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000) * FAST; last = now; clock += dt;
    if (S.scene === STORY) {
      updateStory(dt);
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      drawStory(clock);
      drawFade(dt);
      requestAnimationFrame(frame);
      return;
    }
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    if (S.scene === 0) drawHospital(clock, dt);
    else if (S.scene === 1) drawContacts(clock, dt);
    else if (S.scene === 2) drawForecast(clock, dt);
    else drawNetwork(clock);
    drawFade(dt);
    requestAnimationFrame(frame);
  }

  // soft fade-through when the scene changes
  function drawFade(dt) {
    if (!S.fade) return;
    ctx.fillStyle = rgb(T.corridor, Math.min(1, S.fade * 1.1));
    ctx.fillRect(0, 0, W, H);
    S.fade = reduceMotion ? 0 : Math.max(0, S.fade - dt * 2.8);
  }

  // ---------- tooltip / hover ----------
  function roomAt(ev) {
    if (S.scene === STORY) return null;
    const b = cv.getBoundingClientRect();
    return hitWard((ev.clientX - b.left) / b.width * W, (ev.clientY - b.top) / b.height * H);
  }
  cv.addEventListener("mousemove", (ev) => {
    const g = roomAt(ev); S.hover = g; cv.style.cursor = g ? "pointer" : "default";
    const tip = $("tip"), b = cv.getBoundingClientRect();
    if (!g) { tip.hidden = true; return; }
    tip.style.left = (ev.clientX - b.left) + "px"; tip.style.top = (ev.clientY - b.top) + "px";
    tip.innerHTML = tipHtml(g); tip.hidden = false;
  });
  cv.addEventListener("mouseleave", () => { S.hover = null; $("tip").hidden = true; });
  cv.addEventListener("click", (ev) => {
    const g = roomAt(ev); if (!g) return;
    if (S.scene === 2) { S.fcWard = g; renderPanel(false); }
  });

  function tipHtml(g) {
    const pp = D.people[g];
    let rows = `<div class="row">People<b>${pp.patients} patients · ${pp.staff} staff</b></div>`;
    if (S.scene === 0 || S.scene === 2) {
      const wk = S.scene === 2 ? S.fcWeek : S.week, r = weekOf(wk).groups[g];
      rows += r ? `<div class="row">Tested in week ${wk}<b>${r.tested}</b></div><div class="row">Carry MRSA<b>${r.positive} (${pct(r.p)})</b></div>`
               : `<div class="row">Week ${wk}<b>nobody tested</b></div>`;
    } else if (S.scene === 1) {
      rows += `<div class="row">Contact time inside the ward<b>${pct(D.contacts.within_share[g])}</b></div>`;
    } else if (S.scene === 3) {
      const w = D.superspreader.wards.find((s) => s.ward === g);
      rows += `<div class="row">Halve its contacts: MRSA-days saved<b>${fmt(w.drop)}</b></div>`;
    } else {
      rows += `<div class="row">Usual share carrying MRSA<b>${pct(meanPrev[g])}</b></div>`;
    }
    return `<h4>${g}</h4>${rows}`;
  }

  // ---------- legends under the stage ----------
  const LEGEND = {
    people: `<span><i class="dot pos"></i><b>Coral = carries MRSA</b></span><span><i class="dot neg"></i>Grey = no MRSA</span>
      <span><i class="dot clr"></i>Mint = just cleared</span><span class="legend-note">Each room = 10 people; coral share = real share that week</span>`,
    1: `<span><i class="lg-node"></i>Circle = a ward (bigger = more people)</span><span><i class="lg-ring"></i>Ring = contact time kept inside</span>
      <span><i class="lg-line"></i>Line = contact between wards (thicker = more)</span>`,
    3: `<span><i class="lg-node"></i>Number = MRSA-days saved by halving that ward's contacts</span><span><i class="lg-line" style="background:var(--pos)"></i>Red lines = the #1 ward's contacts</span>`,
    4: `<span><i class="lg-node" style="box-shadow:0 0 0 3px var(--safe)"></i>Green ring + shield = targeted ward</span><span><i class="lg-line"></i>Its lines thin out by the cut</span>
      <span class="legend-note">Centre = MRSA-days avoided</span>`,
  };

  // ---------- scenes ----------
  const SCENES = [
    { id: STORY, name: "How it spreads", render: sceneStory, bar: storyBar },
    { id: 0, name: "Hospital", render: sceneHospital, bar: spreadBar },
    { id: 1, name: "Contacts", render: sceneContacts, bar: contactsBar },
    { id: 2, name: "Forecast", render: sceneForecast, bar: forecastBar },
    { id: 3, name: "Superspreader", render: sceneSuper, bar: () => `<span class="bar-hint">The number in each circle: MRSA-days saved if that ward's contacts are halved.</span>` },
    { id: 4, name: "Intervention", render: sceneIntervention, bar: interventionBar },
  ];
  const topKoopWard = [...D.superspreader.wards].sort((a, b) => b.koopman - a.koopman)[0].ward;
  const topSpreadWard = [...D.superspreader.wards].sort((a, b) => b.drop - a.drop)[0].ward;

  function renderSteps() {
    $("steps").innerHTML = `<span class="slider" id="navSlider"></span>` + SCENES.map((s, i) => `<button class="step ${i === S.pos ? "on" : i < S.pos ? "done" : ""}" data-i="${i}" title="${s.name}"><b>${i + 1}</b><span>${s.name}</span></button>`).join("");
    $("steps").querySelectorAll(".step").forEach((b) => b.onclick = () => go(+b.dataset.i));
    placeSlider(); updateProgress();
  }
  // the accent pill glides under the active scene button
  let sliderX = null;
  function placeSlider() {
    const nav = $("steps"), on = nav.querySelector(".step.on"), sl = $("navSlider");
    if (!on || !sl) return;
    const x = on.offsetLeft, w = on.offsetWidth;
    if (sliderX != null) { sl.style.transition = "none"; sl.style.transform = `translateX(${sliderX}px)`; sl.style.width = sliderW + "px"; sl.offsetWidth; sl.style.transition = ""; }
    sl.style.transform = `translateX(${x}px)`; sl.style.width = w + "px"; sliderX = x; sliderW = w;
  }
  let sliderW = 0;
  window.addEventListener("resize", () => { sliderX = null; placeSlider(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { sliderX = null; placeSlider(); });
  function updateProgress() {
    const part = S.scene === STORY ? (SS.step + 1) / STEPS.length : 1;
    $("progressFill").style.width = ((S.pos + part) / SCENES.length * 100).toFixed(1) + "%";
  }
  function go(i) {
    S.pos = clamp(i, 0, SCENES.length - 1); S.scene = SCENES[S.pos].id; S.playing = (S.scene === 0 || S.scene === 1 || S.scene === 2) && !reduceMotion; S.playAcc = 0;
    if (S.scene === 1) csReset();
    if (S.scene === 2) Object.assign(FS, { wi: Math.max(0, FC_WEEKS.indexOf(13)), i: 0, t: 0 }), S.fcWeek = FC_WEEKS[FS.wi];
    S.hover = null; $("tip").hidden = true;
    if (S.scene === STORY) { SS.step = 0; SS.acc = 0; SS.since = 0; SS.playing = true; }
    $("legend").hidden = S.scene === STORY || S.scene === 2;
    $("legend").innerHTML = LEGEND[S.scene === 0 ? "people" : S.scene] || "";
    S.fade = 1; // canvas fades through on every scene change
    renderSteps(); renderBar(); renderPanel(true);
  }
  function renderBar() { $("stageBar").innerHTML = SCENES[S.pos].bar(); wireBar(); }
  function renderPanel(animate) {
    const p = $("panel");
    const arrow = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`;
    let label;
    if (S.scene === STORY && SS.step < STEPS.length - 1) label = "Next step";
    else label = S.pos < SCENES.length - 1 ? `Next: ${SCENES[S.pos + 1].name}` : "Back to start";
    const where = `Scene ${S.pos + 1} of ${SCENES.length}`;
    p.innerHTML = `<div class="${animate ? "fade-in" : ""}" style="display:flex;flex-direction:column;flex:1">${SCENES[S.pos].render()}</div>
      <div class="panel-nav"><span class="where">${where}</span><button class="nextbtn" id="nextBtn">${label}${arrow}</button></div>`;
    updateProgress();
    $("nextBtn").onclick = () => {
      if (S.scene === STORY && SS.step < STEPS.length - 1) { SS.playing = false; storyGo(SS.step + 1); }
      else go(S.pos < SCENES.length - 1 ? S.pos + 1 : 0);
    };
    wirePanel();
  }

  // ----- story bar + panel -----
  function storyBar() {
    return `<button class="play ghost-btn" id="prevStep" aria-label="Previous step"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      <button class="play" id="storyPlay" aria-label="Play or pause the story">${SS.playing ? playIconPause() : playIconPlay()}</button>
      <button class="play ghost-btn" id="nextStep" aria-label="Next step"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      <div class="dots">${STEPS.map((_, i) => `<button class="sdot ${i === SS.step ? "on" : i < SS.step ? "done" : ""}" data-step="${i}" aria-label="Step ${i + 1}"></button>`).join("")}</div>
      <span class="step-count">Step ${SS.step + 1} of ${STEPS.length}${SS.playing ? '<span class="live">auto</span>' : ""}</span>`;
  }
  function sceneStory() {
    const step = STEPS[SS.step];
    const who = ["A", "B", "C"].map((w) => {
      const shown = w in step.st, on = shown && step.st[w] === 1;
      return `<li><span>${w === "B" ? "Staff" : "Patient"} ${w}</span><b style="color:${!shown ? "var(--muted)" : on ? "var(--pos)" : "var(--ink)"}">${!shown ? "not met yet" : on ? "carries MRSA" : "no MRSA"}</b></li>`;
    }).join("");
    return `<p class="kicker">How MRSA spreads · step ${SS.step + 1} of ${STEPS.length}</p>
      <h2 style="font-size:28px">${step.title}</h2>
      <p style="font-size:16px;line-height:1.6">${step.text}</p>
      <div class="chart-title" style="margin-top:6px">Right now <span>${fmtD(toDay(step.date), true)}</span></div>
      <ul class="list">${who}</ul>
      ${step.final ? `<div class="callout honest">Search result: <b>${ST.n_chains}</b> chains like this in the data, <b>${ST.n_cross_ward}</b> crossing wards. Staff mostly work in one ward, so traceable spread stays inside wards; the next scenes show the whole hospital.</div>` :
        `<div class="callout honest">Real people from the I-Bird data, shown only as A, B and C. The order of events is real; who infected whom is <b>not</b> known.</div>`}`;
  }

  // ----- bars under the stage -----
  const playIcon = () => S.playing
    ? `<svg viewBox="0 0 24 24" width="18" height="18"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>`
    : `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>`;
  function weekBar() {
    const n = D.weeks.length, cal = holdStart;
    return `<button class="play" id="playBtn" aria-label="Play or pause the weeks">${playIcon()}</button>
      <div class="week-info"><b id="wkLabel"></b><span id="wkDate"></span></div>
      <div class="slider-wrap"><input type="range" id="wkSlider" min="0" max="${n - 1}" value="${S.week}" aria-label="Week">
        <div class="phase-row"><span style="flex:${cal}">calibration weeks 0–${cal - 1}</span><span class="hold" style="flex:${n - cal}">held out ${cal}–${n - 1}</span></div></div>`;
  }
  function contactsBar() {
    return `<button class="play ghost-btn" id="csPrev" aria-label="Previous step"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      <button class="play" id="playBtn" aria-label="Play or pause">${playIcon()}</button>
      <button class="play ghost-btn" id="csNext" aria-label="Next step"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      <div class="seq-cap"><span class="seq-step" id="seqStep">${CS.i + 1} / ${CSTEPS.length}</span><span id="seqCaption">${CSTEPS[CS.i].cap}</span></div>`;
  }
  function spreadBar() {
    return `<button class="play" id="playBtn" aria-label="Play or pause">${playIcon()}</button>
      <div class="week-info"><b id="wkLabel"></b><span id="wkDate"></span></div>
      <div class="seq-cap"><span class="seq-step" id="seqStep"></span><span id="seqCaption">${SEQ.caption || ""}</span></div>
      <input type="range" class="seq-slider" id="wkSlider" min="0" max="${D.weeks.length - 1}" value="${S.week}" aria-label="Week">`;
  }
  function forecastBar() {
    const prev = `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    const next = `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    return `<button class="play ghost-btn" id="fsPrev" aria-label="Previous step">${prev}</button>
      <button class="play" id="playBtn" aria-label="Play or pause">${playIcon()}</button>
      <button class="play ghost-btn" id="fsNext" aria-label="Next step">${next}</button>
      <div class="seq-cap"><span class="seq-step" id="seqStep">${FS.i < FSTEPS.length ? `${FS.i + 1} / ${FSTEPS.length}` : "verdict"}</span><span id="seqCaption">${fsStep().cap(S.fcWeek, weekScore(S.fcWeek))}</span></div>
      <div class="chips">${FC_WEEKS.map((w) => `<button class="chip ${w === S.fcWeek ? "on" : ""}" data-fw="${w}">${w}</button>`).join("")}</div>`;
  }
  function interventionBar() {
    return `<span class="bar-label">Wards</span><div class="chips">${[1, 2].map((k) => `<button class="chip ${k === S.k ? "on" : ""}" data-k="${k}">${k}</button>`).join("")}</div>
      <span class="bar-label" style="margin-left:10px">Contact cut</span><div class="chips">${[0.25, 0.5, 0.75].map((r) => `<button class="chip ${r === S.R ? "on" : ""}" data-r="${r}">${r * 100}%</button>`).join("")}</div>`;
  }
  const playIconPlay = () => `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>`;
  const playIconPause = () => `<svg viewBox="0 0 24 24" width="18" height="18"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>`;
  function wireBar() {
    if ($("csPrev")) {
      $("csPrev").onclick = () => { S.playing = false; $("playBtn").innerHTML = playIcon(); csGo(CS.i - 1); };
      $("csNext").onclick = () => { S.playing = false; $("playBtn").innerHTML = playIcon(); csGo(CS.i + 1); };
    }
    if ($("storyPlay")) {
      $("storyPlay").onclick = () => { SS.playing = !SS.playing; SS.acc = 0; renderBar(); };
      $("prevStep").onclick = () => { SS.playing = false; storyGo(SS.step - 1); };
      $("nextStep").onclick = () => { SS.playing = false; storyGo(SS.step + 1); };
      document.querySelectorAll("[data-step]").forEach((b) => b.onclick = () => { SS.playing = false; storyGo(+b.dataset.step); });
    }
    const pb = $("playBtn");
    if (pb) pb.onclick = () => { S.playing = !S.playing; pb.innerHTML = playIcon(); };
    const sl = $("wkSlider");
    if (sl) { sl.oninput = () => { S.week = +sl.value; S.playing = false; $("playBtn").innerHTML = playIcon(); syncWeekUI(); }; syncWeekUI(); }
    document.querySelectorAll("[data-fw]").forEach((b) => b.onclick = () => { fsGo(FC_WEEKS.indexOf(+b.dataset.fw), 0); });
    if ($("fsPrev")) {
      $("fsPrev").onclick = () => { S.playing = false; $("playBtn").innerHTML = playIcon(); fsGo(FS.wi, FS.i - 1); };
      $("fsNext").onclick = () => { S.playing = false; $("playBtn").innerHTML = playIcon(); fsGo(FS.wi, FS.i + 1); };
    }
    document.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => { S.k = +b.dataset.k; renderBar(); renderPanel(false); });
    document.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => { S.R = +b.dataset.r; renderBar(); renderPanel(false); });
  }
  function syncWeekUI() {
    const wk = weekOf(S.week);
    if ($("wkLabel")) $("wkLabel").textContent = `Week ${S.week}`;
    if ($("wkDate")) $("wkDate").textContent = `from Mon ${wk.monday}`;
    if ($("wkSlider")) $("wkSlider").value = S.week;
    const ov = $("ovNow"); if (ov) ov.textContent = pct(overall[S.week]);
    if ($("newNow")) { const t = weekTotals(S.week); $("newNow").textContent = "+" + t.new; $("clrNow").textContent = "−" + t.cleared; $("stillNow").textContent = t.still + t.first; }
    const dot = $("sparkDot"); if (dot) { const p = sparkPos(S.week); dot.setAttribute("cx", p[0]); dot.setAttribute("cy", p[1]); }
  }

  // ----- small SVG chart helpers -----
  const SP = { w: 320, h: 110, l: 30, r: 10, t: 10, b: 22 };
  const sparkMax = Math.max(...overall.filter((v) => v != null)) * 1.15;
  function sparkPos(w) {
    const x = SP.l + (SP.w - SP.l - SP.r) * w / (D.weeks.length - 1);
    const v = overall[w] == null ? 0 : overall[w];
    return [x, SP.t + (SP.h - SP.t - SP.b) * (1 - v / sparkMax)];
  }
  function sparkline() {
    const pts = overall.map((v, w) => v == null ? null : sparkPos(w)).filter(Boolean);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const area = d + ` L ${pts[pts.length - 1][0]} ${SP.h - SP.b} L ${pts[0][0]} ${SP.h - SP.b} Z`;
    const hx = sparkPos(holdStart)[0] - 6;
    const ticks = [0, 0.1, 0.2].filter((t) => t < sparkMax).map((t) => { const y = SP.t + (SP.h - SP.t - SP.b) * (1 - t / sparkMax); return `<line x1="${SP.l}" x2="${SP.w - SP.r}" y1="${y}" y2="${y}" stroke="var(--line)"/><text x="${SP.l - 6}" y="${y + 4}" text-anchor="end">${t * 100}%</text>`; }).join("");
    const p = sparkPos(S.week);
    return `<svg class="chart" viewBox="0 0 ${SP.w} ${SP.h}" role="img" aria-label="Hospital-wide MRSA share per week">
      ${ticks}
      <rect x="${hx}" y="${SP.t}" width="${SP.w - SP.r - hx}" height="${SP.h - SP.t - SP.b}" fill="var(--accent-soft)" rx="4"/>
      <path d="${area}" fill="var(--pos-soft)"/><path d="${d}" fill="none" stroke="var(--pos)" stroke-width="2.2" stroke-linejoin="round"/>
      <circle id="sparkDot" cx="${p[0]}" cy="${p[1]}" r="5" fill="var(--surface)" stroke="var(--pos)" stroke-width="2.5" style="transition:cx .4s, cy .4s"/>
      <text x="${SP.l}" y="${SP.h - 5}">wk 0</text><text x="${SP.w - SP.r}" y="${SP.h - 5}" text-anchor="end">wk ${D.weeks.length - 1}</text>
      <text x="${(hx + SP.w - SP.r) / 2}" y="${SP.t + 12}" text-anchor="middle" style="fill:var(--accent)">held out</text></svg>`;
  }

  function fcPoint(model, ward, wk) { return D.forecast.points.find((p) => p.model === model && p.ward === ward && p.landing_week === wk); }
  const MODEL_LABEL = { persistence: "Same as last week", [MODEL]: `Koopman (${MODEL})`, ward_sis: "Ward SIS model", historical_mean: "Historical mean" };
  const MODEL_COLOR = { persistence: "var(--muted)", [MODEL]: "var(--accent)", ward_sis: "var(--staff)", historical_mean: "var(--wall)" };

  function forecastChart(ward) {
    const C = { w: 330, h: 180, l: 34, r: 12, t: 12, b: 26 };
    const wks = [...new Set(D.forecast.points.map((p) => p.landing_week))].sort((a, b) => a - b);
    const x0 = wks[0] - 1, x1 = wks[wks.length - 1];
    const actual = []; for (let w = x0; w <= x1; w++) actual.push([w, prevAt(w, ward)]);
    const series = { persistence: [], [MODEL]: [] };
    Object.keys(series).forEach((m) => wks.forEach((w) => { const p = fcPoint(m, ward, w); if (p) series[m].push([w, p.pred]); }));
    const vals = actual.map((a) => a[1]).concat(...Object.values(series).map((s) => s.map((p) => p[1]))).filter((v) => v != null);
    const ymax = Math.max(0.1, ...vals) * 1.15;
    const X = (w) => C.l + (C.w - C.l - C.r) * (w - x0) / (x1 - x0), Y = (v) => C.t + (C.h - C.t - C.b) * (1 - v / ymax);
    const line = (pts, color, dash, wdt) => {
      const d = pts.filter((p) => p[1] != null).map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${wdt}" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linecap="round" stroke-linejoin="round"/>` +
        pts.filter((p) => p[1] != null).map((p) => `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${wdt + 1}" fill="${color}"/>`).join("");
    };
    const step = ymax > 0.4 ? 0.2 : 0.1;
    let grid = ""; for (let v = 0; v < ymax; v += step) grid += `<line x1="${C.l}" x2="${C.w - C.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${C.l - 6}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text>`;
    let xl = ""; for (let w = x0; w <= x1; w++) xl += `<text x="${X(w)}" y="${C.h - 8}" text-anchor="middle" ${w === S.fcWeek ? 'class="ink"' : ""}>wk ${w}</text>`;
    const cur = `<rect x="${X(S.fcWeek) - 14}" y="${C.t}" width="28" height="${C.h - C.t - C.b}" rx="6" fill="var(--accent-soft)"/>`;
    return `<svg class="chart" viewBox="0 0 ${C.w} ${C.h}" role="img" aria-label="Forecast versus actual for ${ward}">${grid}${cur}${xl}
      ${line(series.persistence, "var(--muted)", "6 4", 1.8)}${line(series[MODEL], "var(--accent)", "", 2.4)}${line(actual, "var(--pos)", "", 2.8)}</svg>
      <div class="legend" style="padding:6px 0 0"><span><i class="dot pos"></i>What happened</span><span><i class="dot" style="background:var(--accent)"></i>Koopman forecast</span><span><i class="dot" style="background:var(--muted)"></i>"Same as last week"</span></div>`;
  }

  // ----- scene panels: one message each -----
  const weekTotals = (w) => {
    const t = { new: 0, cleared: 0, still: 0, first: 0, tested: 0 };
    G.forEach((g) => { const r = trOf(w, g); if (r) Object.keys(t).forEach((k) => { t[k] += r[k]; }); });
    return t;
  };
  const allNew = D.weeks.reduce((s, _, w) => s + weekTotals(w).new, 0), allClr = D.weeks.reduce((s, _, w) => s + weekTotals(w).cleared, 0);
  function sceneHospital() {
    const t = weekTotals(S.week);
    return `<p class="kicker">The whole hospital, week by week</p>
      <h2>One week, one event at a time.</h2>
      <p>A carrier <strong>walks to another ward</strong> and passes MRSA on. Then it spreads <strong>inside a ward</strong>. Then someone <strong style="color:var(--safe)">clears it</strong>. Each room's coral share is the real share that week.</p>
      <div class="flow"><div><b id="newNow" style="color:var(--pos)">+${t.new}</b><span>caught MRSA since<br>their last swab</span></div>
        <div><b id="clrNow" style="color:var(--safe)">−${t.cleared}</b><span>cleared it since<br>their last swab</span></div>
        <div><b id="stillNow">${t.still + t.first}</b><span>still or already<br>carrying</span></div></div>
      ${sparkline()}
      <p class="fine">Over all ${D.weeks.length} weeks: <b>${allNew}</b> people caught MRSA and <b>${allClr}</b> cleared it, so the level stayed steady, as our SIS model assumes. The data does not record who infected whom: the walker and the person they meet are an illustration; routes follow the real contact links.</p>`;
  }

  function sceneContacts() {
    const totalIn = G.reduce((s, g) => s + D.contacts.inside_hours[g], 0);
    const totalBetween = D.contacts.links.reduce((s, l) => s + l.hours, 0) * 2;
    const share = totalIn / (totalIn + totalBetween);
    const top = [...D.contacts.links].sort((a, b) => b.hours - a.hours).slice(0, 3);
    return `<p class="kicker">Who meets whom</p>
      <h2>${Math.round(share * 100)}% of contact time stays inside a ward.</h2>
      <p>Each circle is a ward; its <strong>ring</strong> fills with the share of contact time kept inside. The <strong>lines</strong> between wards are where MRSA can cross.</p>
      <div class="chart-title">The three busiest links <span>contact hours</span></div>
      <ul class="list">${top.map((l) => `<li><div>${l.a} ↔ ${l.b}<div class="mini-bar" style="width:${(l.hours / top[0].hours * 100).toFixed(0)}%"></div></div><b>${fmt(l.hours)} h</b></li>`).join("")}</ul>`;
  }

  function sceneForecast() {
    const r = (m, h) => (D.forecast.rmse.find((x) => x.model === m && x.h === h) || {}).rmse;
    const k1 = r(MODEL, 1), p1 = r("persistence", 1);
    return `<p class="kicker">Forecasting</p>
      <h2>One week ahead, Koopman ties with "same as last week".</h2>
      <div class="vs"><div><b style="color:var(--accent)" data-count="${(k1 * 100).toFixed(1)}" data-dec="1">${(k1 * 100).toFixed(1)}</b><span>Koopman</span></div><i>vs</i><div><b data-count="${(p1 * 100).toFixed(1)}" data-dec="1">${(p1 * 100).toFixed(1)}</b><span>Same as last week</span></div></div>
      <p class="fine" style="margin-top:-6px">Average miss, in percentage points, over the held-out weeks. Lower is better.</p>
      <div class="chart-title">${S.fcWard} <span>click a ward on the left to switch</span></div>
      ${forecastChart(S.fcWard)}`;
  }

  function sceneSuper() {
    const ws = [...D.superspreader.wards].sort((a, b) => b.drop - a.drop);
    const kTop = [...D.superspreader.wards].sort((a, b) => b.koopman - a.koopman)[0].ward;
    const maxHi = Math.max(...ws.map((w) => w.hi));
    const sp = (gt, c) => D.superspreader.spearman.find((s) => s.ground_truth === gt && s.candidate === c);
    const sK = sp("pct50", "koopman_" + MODEL), sD = sp("pct50", "degree_centrality");
    const bars = ws.map((w, i) => `<div class="hbar ${i === 0 ? "top" : ""}">
        <span class="hb-name">${w.ward}${w.ward === kTop ? ' <em>Koopman\'s pick</em>' : ""}</span><b>${fmt(w.drop)}</b>
        <span class="hb-track"><span class="hb-fill" style="width:${w.drop / maxHi * 100}%"></span><span class="hb-ci" style="left:${w.lo / maxHi * 100}%;width:${(w.hi - w.lo) / maxHi * 100}%"></span></span></div>`).join("");
    return `<p class="kicker">The superspreader ward</p>
      <h2>Calming ${ws[0].ward} helps the most, and Koopman picks it.</h2>
      <p>Simulation test: halve one ward's contacts and count the MRSA-days saved.</p>
      ${bars}
      <p class="fine" style="margin-top:12px">Rank agreement with this test: Koopman <b>${sK.spearman_rho.toFixed(2)}</b>, plain contact hours <b>${sD.spearman_rho.toFixed(2)}</b>. Counting contacts works as well; Koopman adds no extra ranking power here.</p>`;
  }

  function sceneIntervention() {
    const strats = [KOOP, "degree_targeted", "random", "whole_hospital"];
    const LABEL = { degree_targeted: "Ward(s) with most contact", [KOOP]: "Koopman's pick", random: "Random ward(s)", whole_hospital: "Whole hospital, thinly" };
    const rows = strats.map((s) => [s, interRow(s)]).filter((x) => x[1]);
    const maxHi = Math.max(...rows.map((x) => x[1].drop_ci_high));
    const cur = interRow(S.strategy) || rows[0][1];
    const pair = D.interventions.pairwise.find((p) => p.reference === "degree_targeted" && p.k === S.k && Math.abs(p.R - S.R) < 1e-9);
    const verdict = pair ? (pair.verdict === "better" ? `Here Koopman's pick saves <b>${fmt(pair.advantage_mean)} more days</b> than the contact-count pick.`
      : `Here Koopman's pick and the contact-count pick ${pair.advantage_mean === 0 ? "choose the <b>same ward</b>" : "are <b>a tie</b>"}.`) : "";
    return `<p class="kicker">Intervention</p>
      <h2>Same effort, aimed at the right ward, works best.</h2>
      <p>Cut contacts by <strong>${S.R * 100}%</strong> in <strong>${S.k} ward${S.k > 1 ? "s" : ""}</strong> (change this under the map), or spread the same effort thinly.</p>
      <div class="big-wrap"><span class="big-number" id="bigNum">0</span><span>MRSA-days avoided<br>${LABEL[S.strategy]} · ${pct(cur.drop_fraction_mean, 1)} of all</span></div>
      <div class="strategy-grid">${rows.map(([s, r]) => `<button class="strat ${s === S.strategy ? "on" : ""}" data-strat="${s}">
          <span class="name">${LABEL[s]}</span><span class="val">${fmt(r.drop_mean)}</span>
          <span class="track"><span class="fill" style="width:${r.drop_mean / maxHi * 100}%"></span></span></button>`).join("")}</div>
      <p class="fine">${verdict} 200 simulated runs per option.</p>`;
  }

  let numAnim = null;
  function tweenNumber(el, to) {
    if (!el) return; const from = +(el.dataset.v || 0), t0 = performance.now(), dur = reduceMotion ? 1 : 700;
    cancelAnimationFrame(numAnim);
    const step = (now) => { const t = clamp((now - t0) / dur, 0, 1), e = 1 - Math.pow(1 - t, 3); el.textContent = fmt(lerp(from, to, e)); if (t < 1) numAnim = requestAnimationFrame(step); else el.dataset.v = to; };
    numAnim = requestAnimationFrame(step);
  }
  let lastBig = 0;
  function wirePanel() {
    document.querySelectorAll("[data-fcward]").forEach((b) => b.onclick = () => { S.fcWard = b.dataset.fcward; renderPanel(false); });
    document.querySelectorAll("[data-strat]").forEach((b) => b.onclick = () => { S.strategy = b.dataset.strat; renderPanel(false); });
    // count-up for headline numbers (only when the panel animates in)
    document.querySelectorAll("#panel .fade-in [data-count]").forEach((el) => {
      const to = +el.dataset.count, dec = +(el.dataset.dec || 0), t0 = performance.now(), dur = reduceMotion ? 1 : 900;
      const tick = (now) => { const t = clamp((now - t0) / dur, 0, 1), e = 1 - Math.pow(1 - t, 3); el.textContent = (to * e).toFixed(dec); if (t < 1) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    });
    const big = $("bigNum");
    if (big) { big.dataset.v = lastBig; big.textContent = fmt(lastBig); const r = interRow(S.strategy); lastBig = r ? r.drop_mean : 0; tweenNumber(big, lastBig); }
  }

  // ---------- keyboard / theme ----------
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" && e.key !== " ") return;
    if (S.scene === STORY && (e.key === "ArrowRight" || e.key === "ArrowLeft" || e.key === " ")) {
      e.preventDefault();
      if (e.key === " ") { SS.playing = !SS.playing; SS.acc = 0; renderBar(); return; }
      SS.playing = false;
      if (e.key === "ArrowRight") { if (SS.step < STEPS.length - 1) storyGo(SS.step + 1); else if (!LOCK) go(S.pos + 1); }
      else if (SS.step > 0) storyGo(SS.step - 1);
      return;
    }
    if (LOCK) return; // embedded: the host app owns scene navigation
    if (e.key === "ArrowRight") go(S.pos + 1);
    else if (e.key === "ArrowLeft") go(S.pos - 1);
    else if (e.key === " " && (S.scene === 0 || S.scene === 1)) { e.preventDefault(); S.playing = !S.playing; const pb = $("playBtn"); if (pb) pb.innerHTML = playIcon(); }
  });
  // presentation mode: bigger stage, no footer, fullscreen when the browser allows it
  function togglePresent() {
    const on = document.body.classList.toggle("present");
    try {
      if (on && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
      else if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    } catch (e) { /* fullscreen not available */ }
    sliderX = null; setTimeout(placeSlider, 60);
  }
  $("presentBtn").onclick = togglePresent;
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) document.body.classList.remove("present"); sliderX = null; setTimeout(placeSlider, 60); });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (LOCK) return;
    if (e.key === "f" || e.key === "F") togglePresent();
    if (e.key === "t" || e.key === "T") $("themeBtn").click();
  });
  $("themeBtn").onclick = () => {
    const root = document.documentElement, dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark"; readTokens();
    try { localStorage.setItem("p30-theme", root.dataset.theme); } catch (e) { /* storage unavailable */ }
  };
  if (!LOCK) { try { const t = localStorage.getItem("p30-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* storage unavailable */ } }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readTokens);

  $("perFigure").textContent = `Each figure ≈ ${D.people_per_figure} people`;
  readTokens(); resize(); go(clamp(window.DEMO_START | 0, 0, SCENES.length - 1));

  // Embedded: size the host's iframe to the content, so there is no empty
  // band and no inner scrollbar at any window width (same-origin frame).
  // Embedded: follow the host app's light / dark theme (read from its background).
  function syncHostTheme() {
    try {
      const host = window.parent.document, el = host.querySelector(".stApp") || host.body;
      const m = getComputedStyle(el).backgroundColor.match(/[\d.]+/g);
      if (!m) return;
      const t = 0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2] < 128 ? "dark" : "light";
      if (document.documentElement.dataset.theme !== t) { document.documentElement.dataset.theme = t; readTokens(); }
    } catch (e) { /* cross-origin host: keep the system theme */ }
  }
  if (LOCK) { syncHostTheme(); setInterval(syncHostTheme, 1200); }

  if (LOCK && window.frameElement) {
    const fit = () => {
      try { window.frameElement.style.height = Math.ceil(document.querySelector(".layout").getBoundingClientRect().height + 6) + "px"; }
      catch (e) { /* cross-origin host: keep the host's fixed height */ }
    };
    new ResizeObserver(fit).observe(document.body);
    fit();
  }
  requestAnimationFrame(frame);
})();
