/* MRSA ward map: animated, read-only view of the saved P30 results.
   All numbers come from window.DEMO_DATA (written by src/demo_data.py).
   The walking figures are decoration; their colours follow the real data. */
(() => {
  "use strict";
  const D = window.DEMO_DATA;
  if (!D) { document.body.innerHTML = "<p style='padding:40px'>demo_data.js missing: run <code>python -m src.demo_data</code> from the project root.</p>"; return; }

  const G = D.groups;
  const MODEL = D.model;
  const KOOP = "koopman_targeted_" + MODEL;
  const W = 1000, H = 640;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
    const cs = getComputedStyle(document.documentElement);
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

  // ---------- floor layout (1000 x 640 units) ----------
  const CORR_Y = 320;
  const ROOM = {};
  const cols = [24, 350, 676], RW = 300, RH = 252;
  G.forEach((g, i) => {
    const top = i < 3, x = cols[i % 3], y = top ? 22 : 366;
    const door = { x: x + RW / 2, y: top ? y + RH : y };
    const area = { x0: x + 22, x1: x + RW - 22, y0: y + 92, y1: y + RH - 14 };
    ROOM[g] = { g, x, y, w: RW, h: RH, top, door, area, staffRoom: D.people[g].patients === 0 };
  });

  // ---------- figures ----------
  const figures = [];
  G.forEach((g) => {
    const pp = D.people[g], n = Math.round((pp.patients + pp.staff) / D.people_per_figure);
    const nPat = Math.round(n * pp.patients / (pp.patients + pp.staff));
    const roles = [...Array(n).keys()].map((k) => (k < nPat ? "patient" : "staff")).sort(() => rand() - 0.5);
    // Tidy rows: slot = rank, and the first k ranks are the MRSA carriers,
    // so red figures always fill the front of the room (easy to count).
    const a = ROOM[g].area, cols = 9, dx = (a.x1 - a.x0) / (cols - 1);
    const rows = Math.ceil(n / cols), dy = Math.min(52, (a.y1 - a.y0 - 34) / Math.max(1, rows - 1));
    for (let k = 0; k < n; k++) {
      const col = k % cols, row = Math.floor(k / cols);
      const sx = a.x0 + col * dx, sy = a.y0 + 34 + row * dy;
      figures.push({
        g, role: roles[k], rank: k, n, sx, sy, x: sx, y: sy, moving: false,
        phase: rr(0, 6.28), skin: "skin" + (1 + Math.floor(rand() * 4)), blink: rr(1, 5), dir: rand() < 0.5 ? -1 : 1,
        c: 0, u: 0, hairStyle: Math.floor(rand() * 3), turnT: rr(2, 8),
      });
    }
  });
  const nFigByWard = {}; G.forEach((g) => { nFigByWard[g] = figures.filter((f) => f.g === g).length; });

  const visitors = [];
  function pathBetween(a, b) {
    const A = ROOM[a], B = ROOM[b];
    const pA = { x: rr(A.area.x0 + 30, A.area.x1 - 30), y: A.top ? A.area.y1 - 10 : A.area.y0 + 10 };
    const pB = { x: rr(B.area.x0 + 30, B.area.x1 - 30), y: B.top ? B.area.y1 - 10 : B.area.y0 + 10 };
    const lane = CORR_Y + rr(-16, 16);
    return [pA, { x: A.door.x, y: A.door.y + (A.top ? -6 : 6) }, { x: A.door.x, y: lane }, { x: B.door.x, y: lane }, { x: B.door.x, y: B.door.y + (B.top ? -6 : 6) }, pB];
  }
  function spawnVisitor(a, b) {
    const p = prevForMap(a);
    visitors.push({
      g: a, role: "staff", path: pathBetween(a, b), seg: 0, s: 0, fwd: true, stay: 0, done: false,
      x: 0, y: 0, phase: rr(0, 6), skin: "skin" + (1 + Math.floor(rand() * 4)), blink: rr(1, 5), dir: 1,
      c: p != null && rand() < p ? 1 : 0, u: 0, rank: 0, moving: true, hairStyle: 0, visitor: true, trail: [], trailT: 0,
    });
    const v = visitors[visitors.length - 1]; v.x = v.path[0].x; v.y = v.path[0].y;
  }

  // ---------- state ----------
  const STORY = 5; // internal id of the story scene (shown first)
  const S = {
    scene: STORY, pos: 0, week: 5, playing: false, playAcc: 0, hover: null,
    fcWard: "Menard 2", fcWeek: 13,
    k: 1, R: 0.5, strategy: KOOP,
  };

  function prevForMap(g) {
    if (S.scene === 2) return prevAt(S.fcWeek, g);
    if (S.scene === 3 || S.scene === 4) return meanPrev[g];
    return prevAt(S.week, g);
  }
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

  function drawFloor(time) {
    ctx.fillStyle = rgb(T.corridor); ctx.fillRect(0, 0, W, H);
    // corridor lane markings
    ctx.strokeStyle = rgb(T.wall, 0.5); ctx.setLineDash([10, 12]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(20, CORR_Y); ctx.lineTo(W - 20, CORR_Y); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = rgb(T.muted, 0.75); ctx.font = "600 11px Inter, system-ui, sans-serif"; ctx.textAlign = "left";
    ctx.fillText("CORRIDOR", 28, CORR_Y - 8);

    const targets = targetedWards();
    G.forEach((g) => {
      const r = ROOM[g];
      ctx.save(); ctx.globalAlpha = r.fa == null ? 1 : r.fa; // spotlight: rooms the scene is not about fade back
      // soft drop shadow gives the rooms depth
      ctx.save(); ctx.shadowColor = "rgba(0,0,0,0.16)"; ctx.shadowBlur = 22; ctx.shadowOffsetY = 8;
      roundRect(r.x, r.y, r.w, r.h, 18); ctx.fillStyle = rgb(T.floor); ctx.fill(); ctx.restore();
      ctx.save();
      roundRect(r.x, r.y, r.w, r.h, 18); ctx.fillStyle = rgb(T.floor); ctx.fill();
      ctx.clip();
      // tiles
      ctx.strokeStyle = rgb(T["floor-tile"]); ctx.lineWidth = 1;
      for (let x = r.x + 25; x < r.x + r.w; x += 25) { ctx.beginPath(); ctx.moveTo(x, r.y); ctx.lineTo(x, r.y + r.h); ctx.stroke(); }
      for (let y = r.y + 25; y < r.y + r.h; y += 25) { ctx.beginPath(); ctx.moveTo(r.x, y); ctx.lineTo(r.x + r.w, y); ctx.stroke(); }
      ctx.restore();

      // walls
      const low = isLow(g), missing = prevForMap(g) == null;
      roundRect(r.x, r.y, r.w, r.h, 18);
      ctx.lineWidth = 2; ctx.strokeStyle = rgb(T.wall);
      if (low || missing) ctx.setLineDash([7, 6]);
      ctx.stroke(); ctx.setLineDash([]);
      // door gap
      ctx.fillStyle = rgb(T.corridor); ctx.fillRect(r.door.x - 22, r.door.y - 3, 44, 6);

      // hover outline
      if (S.hover === g) { roundRect(r.x - 3, r.y - 3, r.w + 6, r.h + 6, 21); ctx.strokeStyle = rgb(T.accent, 0.8); ctx.lineWidth = 2.5; ctx.stroke(); }

      // intervention barrier
      if (targets.includes(g)) {
        const pulse = reduceMotion ? 0.5 : 0.5 + 0.5 * Math.sin(time * 2.4);
        roundRect(r.x - 4, r.y - 4, r.w + 8, r.h + 8, 22);
        ctx.strokeStyle = rgb(T.safe, 0.55 + 0.35 * pulse); ctx.lineWidth = S.strategy === "whole_hospital" ? 2 : 4; ctx.stroke();
        if (S.strategy !== "whole_hospital") drawShield(r.x + r.w - 30, r.y + 30);
      }
      // superspreader ripple
      if (S.scene === 3 && g === topSpreadWard && !reduceMotion) {
        for (let i = 0; i < 3; i++) {
          const ph = ((time * 0.45 + i / 3) % 1);
          ctx.beginPath(); ctx.arc(r.x + r.w / 2, r.y + r.h / 2 + 20, 40 + ph * 170, 0, Math.PI * 2);
          ctx.strokeStyle = rgb(T.accent, 0.35 * (1 - ph)); ctx.lineWidth = 2; ctx.stroke();
        }
      }
      drawRoomLabel(r);
      ctx.restore();
    });
  }

  // how bright each room is in the current scene (1 = in focus)
  function focusOf(g) {
    if (S.hover) return g === S.hover ? 1 : 0.45;
    if (S.scene === 2) return g === S.fcWard ? 1 : 0.3;
    if (S.scene === 3) return g === topSpreadWard ? 1 : 0.4;
    if (S.scene === 4) {
      const t = targetedWards();
      return !t.length || S.strategy === "whole_hospital" ? 1 : (t.includes(g) ? 1 : 0.4);
    }
    return 1;
  }

  function drawShield(x, y) {
    ctx.save(); ctx.translate(x, y);
    ctx.beginPath(); ctx.moveTo(0, -13); ctx.lineTo(11, -8); ctx.lineTo(10, 3); ctx.quadraticCurveTo(7, 11, 0, 15); ctx.quadraticCurveTo(-7, 11, -10, 3); ctx.lineTo(-11, -8); ctx.closePath();
    ctx.fillStyle = rgb(T.safe); ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.moveTo(-5, 1); ctx.lineTo(-1, 5); ctx.lineTo(6, -4); ctx.stroke();
    ctx.restore();
  }

  function isLow(g) {
    if (S.scene !== 0 && S.scene !== 1 && S.scene !== 2) return false;
    const r = weekOf(S.scene === 2 ? S.fcWeek : S.week).groups[g];
    return r ? r.low_n : false;
  }

  function drawRoomLabel(r) {
    const g = r.g, p = prevForMap(g);
    const lx = r.x + 18, ly = r.top ? r.y + 30 : r.y + 30;
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "700 17px Inter, system-ui, sans-serif";
    ctx.fillText(g, lx, ly);
    // "#1 spreader" badge in the superspreader scene (ground truth from simulation)
    if (S.scene === 3 && g === topSpreadWard) {
      const nw = ctx.measureText(g).width, bx = lx + nw + 10, label = "#1 SPREADER";
      ctx.font = "750 10.5px Inter, system-ui, sans-serif"; const bw = ctx.measureText(label).width + 16;
      roundRect(bx, ly - 14, bw, 19, 9.5); ctx.fillStyle = rgb(T.pos); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillText(label, bx + 8, ly);
    }
    ctx.fillStyle = rgb(T.muted); ctx.font = "500 12px Inter, system-ui, sans-serif";
    const pp = D.people[g];
    let sub = pp.patients ? `${pp.patients} patients · ${pp.staff} staff` : `${pp.staff} staff (no beds)`;
    const wkRow = S.scene <= 2 ? weekOf(S.scene === 2 ? S.fcWeek : S.week).groups[g] : null;
    if (S.scene <= 1) sub = wkRow ? `${wkRow.positive} of ${wkRow.tested} tested carry MRSA` : "nobody tested this week";
    if (S.scene === 2) {
      const f = fcPoint(MODEL, g, S.fcWeek);
      sub = f ? `real share · Koopman forecast ${pct(f.pred)}` : "real share · no forecast";
    } else if (S.scene === 3) {
      const w = D.superspreader.wards.find((s) => s.ward === g);
      sub = `halving its contacts saves ${fmt(w.drop)} MRSA-days`;
    } else if (S.scene === 4) sub = "usual share carrying MRSA";
    ctx.fillText(sub, lx, ly + 18);
    // carrier share bar
    const bx0 = lx, bw0 = r.w - 36, by0 = ly + 30;
    roundRect(bx0, by0, bw0, 6, 3); ctx.fillStyle = rgb(T.line); ctx.fill();
    if (p != null) {
      r.barP = r.barP == null ? p : lerp(r.barP, p, 0.12);
      if (r.barP > 0.003) { roundRect(bx0, by0, Math.max(6, bw0 * r.barP), 6, 3); ctx.fillStyle = rgb(T.pos); ctx.fill(); }
    }

    ctx.textAlign = "right";
    const rx = r.x + r.w - 18;
    if (p == null) {
      ctx.fillStyle = rgb(T.muted); ctx.font = "600 13px Inter, system-ui, sans-serif"; ctx.fillText("not tested", rx, ly);
    } else {
      ctx.fillStyle = rgb(mix(T.ink, T.pos, clamp(p * 2.2, 0, 1))); ctx.font = "750 24px Inter, system-ui, sans-serif";
      ctx.fillText(pct(p), rx - (S.scene === 4 && targetedWards().includes(g) && S.strategy !== "whole_hospital" ? 30 : 0), ly + 2);
      if (isLow(g)) { ctx.fillStyle = rgb(T.muted); ctx.font = "600 10.5px Inter, system-ui, sans-serif"; ctx.fillText("few tests", rx, ly + 18); }
    }
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

  function drawLinks(time) {
    if (S.scene !== 1) return;
    const top = [...D.contacts.links].sort((a, b) => b.hours - a.hours).slice(0, 3);
    top.forEach((l, i) => {
      const A = ROOM[l.a], B = ROOM[l.b];
      const ax = A.door.x, ay = A.door.y + (A.top ? -40 : 40), bx = B.door.x, by = B.door.y + (B.top ? -40 : 40);
      const cx = (ax + bx) / 2, cy = CORR_Y + (A.top === B.top ? (A.top ? 70 : -70) : 0);
      const w = 3 + 7 * (l.hours / linkMax);
      ctx.strokeStyle = rgb(T.accent, 0.3); ctx.lineWidth = w; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.quadraticCurveTo(cx, cy, bx, by); ctx.stroke();
      {
        const mx = 0.25 * ax + 0.5 * cx + 0.25 * bx, my = 0.25 * ay + 0.5 * cy + 0.25 * by;
        const label = fmt(l.hours) + " h";
        ctx.font = "650 11.5px Inter, system-ui, sans-serif"; ctx.textAlign = "center";
        const tw = ctx.measureText(label).width + 14;
        roundRect(mx - tw / 2, my - 11, tw, 22, 11); ctx.fillStyle = rgb(T.surface, 0.95); ctx.fill();
        ctx.strokeStyle = rgb(T.accent, 0.5); ctx.lineWidth = 1; ctx.stroke();
        ctx.fillStyle = rgb(T.ink); ctx.fillText(label, mx, my + 4);
      }
    });
  }

  // ---------- simulation of decoration ----------
  let firstFrame = true;
  function updateFigures(dt) {
    // colonised count per ward follows the data; same people stay positive (fixed rank)
    const targets = {};
    G.forEach((g) => { const p = prevForMap(g); targets[g] = p == null ? null : Math.round(p * nFigByWard[g]); });
    figures.forEach((f) => {
      const k = targets[f.g];
      const wantU = k == null ? 1 : 0, wantC = k == null ? 0 : (f.rank < k ? 1 : 0);
      // stagger the colour change along the row so a week change "ripples"
      const rate = reduceMotion || firstFrame ? 1 : clamp(dt * 3.2, 0, 1);
      if (firstFrame) f.delay = 0;
      f.u = lerp(f.u, wantU, rate);
      f.delay = f.c < 0.5 !== (wantC < 0.5) ? (f.delay == null ? f.rank * 0.035 : f.delay - dt) : null;
      if (f.delay == null || f.delay <= 0) f.c = lerp(f.c, wantC, rate);
      f.blink -= dt; if (f.blink < 0) f.blink = rr(2.5, 6);
      // stand in their slot with a gentle idle sway; look around now and then
      f.phase += dt * 2; f.x = f.sx; f.y = f.sy; f.moving = false;
      f.turnT -= dt; if (f.turnT < 0) { f.turnT = rr(2, 8); f.dir = -f.dir; }
    });
    firstFrame = false;
    G.forEach((g) => { const r = ROOM[g], want = focusOf(g); r.fa = r.fa == null ? want : lerp(r.fa, want, reduceMotion ? 1 : clamp(dt * 5, 0, 1)); });
    figures.forEach((f) => { f.alpha = ROOM[f.g].fa; });
  }

  function updateVisitors(dt) {
    if (reduceMotion) { visitors.length = 0; return; }
    const base = S.scene === 1 ? 1.2 : S.scene === 2 ? 0 : 0.4; // visits per second at the busiest link (none while forecasting)
    const cap = S.scene === 1 ? 7 : 4;
    const tw = targetedWards();
    D.contacts.links.forEach((l) => {
      let rate = base * l.hours / linkMax;
      if (S.scene === 4 && (tw.includes(l.a) || tw.includes(l.b))) rate *= (1 - S.R);
      if (visitors.length < cap && rand() < rate * dt) {
        // in the spreader scene, walkers leave from the #1 spreader ward
        if (S.scene === 3 && (l.a === topSpreadWard || l.b === topSpreadWard)) spawnVisitor(topSpreadWard, l.a === topSpreadWard ? l.b : l.a);
        else rand() < 0.5 ? spawnVisitor(l.a, l.b) : spawnVisitor(l.b, l.a);
      }
    });
    visitors.forEach((v) => {
      if (v.stay > 0) { v.stay -= dt; v.moving = false; if (v.stay <= 0) { v.fwd = false; v.seg = v.path.length - 1; } return; }
      const i = v.seg, j = v.fwd ? i + 1 : i - 1;
      if (j < 0 || j >= v.path.length) { if (v.fwd) v.stay = rr(1, 2.5); else v.done = true; return; }
      const P = v.path[j], dx = P.x - v.x, dy = P.y - v.y, d = Math.hypot(dx, dy);
      v.moving = true; v.dir = dx >= 0 ? 1 : -1; v.phase += dt * 12; v.blink -= dt; if (v.blink < 0) v.blink = rr(2, 6);
      const m = Math.min(d, 70 * dt);
      if (d < 1) { v.seg = j; return; }
      v.x += dx / d * m; v.y += dy / d * m;
      if (v.c > 0.5 && v.fwd) { v.trailT -= dt; if (v.trailT <= 0) { v.trailT = 0.05; v.trail.push({ x: v.x, y: v.y }); if (v.trail.length > 40) v.trail.shift(); } }
    });
    for (let i = visitors.length - 1; i >= 0; i--) if (visitors[i].done) visitors.splice(i, 1);
  }

  // red dotted footprints behind a walker who carries MRSA between wards
  function drawTrails() {
    visitors.forEach((v) => {
      const n = v.trail.length;
      v.trail.forEach((p, i) => { if (i % 2) return; ctx.fillStyle = rgb(T.pos, 0.55 * (i + 1) / n); ctx.beginPath(); ctx.arc(p.x, p.y - 2, 2.2, 0, 7); ctx.fill(); });
    });
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
    ctx.font = font || "650 13px Inter, system-ui, sans-serif"; const w = ctx.measureText(text).width + 22;
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
    ctx.fillStyle = positive ? "#fff" : rgb(T.ink); ctx.font = "750 14px Inter, system-ui, sans-serif"; ctx.textAlign = "left";
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
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.ink); ctx.font = "750 20px Inter, system-ui, sans-serif"; ctx.fillText(ST.ward + " ward", R.x + 24, R.y + 38);
    ctx.fillStyle = rgb(T.muted); ctx.font = "500 13px Inter, system-ui, sans-serif"; ctx.fillText("Three real people from the data (anonymised). Everyone else is faded.", R.x + 24, R.y + 58);
    pill(R.x + R.w - 92, R.y + 34, fmtD(SS.day, true), rgb(T.ink), rgb(T.surface), "700 14px Inter, system-ui, sans-serif");

    // contact: ring around the pair + minute counter + possible-route particles
    if (step.contact) {
      const [a, b] = step.contact === "AB" ? [storyPeople[0], storyPeople[1]] : [storyPeople[1], storyPeople[2]];
      const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2 - 40, k = clamp(SS.since / 0.8, 0, 1);
      ctx.save(); ctx.globalAlpha = k;
      ctx.beginPath(); ctx.ellipse(cx, cy, 160, 105, 0, 0, Math.PI * 2); ctx.fillStyle = rgb(T.accent, 0.08); ctx.fill();
      ctx.setLineDash([8, 7]); ctx.lineDashOffset = -time * 20; ctx.strokeStyle = rgb(T.accent, 0.8); ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
      pill(cx, cy - 118, `${fmt(SS.count)} min of contact`, rgb(T.accent), "#fff", "700 14px Inter, system-ui, sans-serif");
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
      ctx.textAlign = "center"; ctx.fillStyle = rgb(T.ink); ctx.font = "750 17px Inter, system-ui, sans-serif"; ctx.fillText(name, p.x, p.y + 30);
      ctx.fillStyle = p.c > 0.5 ? rgb(T.pos) : rgb(T.muted); ctx.font = "600 13px Inter, system-ui, sans-serif"; ctx.fillText(status, p.x, p.y + 48);
      ctx.restore();
      if (step.badge && p.who in step.badge) drawSwabBubble(p, step.badge[p.who] === 1, SS.since - 0.3);
    });

    drawStoryTimeline();
  }

  function drawStoryTimeline() {
    const L = 120, Rr = 960, X = (d) => L + (Rr - L) * (d - t0) / (t1 - t0);
    const lanes = { A: 478, B: 522, C: 566 };
    ctx.textAlign = "left"; ctx.fillStyle = rgb(T.muted); ctx.font = "650 11px Inter, system-ui, sans-serif";
    ctx.fillText("SWABS AND CONTACTS OVER TIME", 24, 452);
    ["A", "B", "C"].forEach((w) => {
      const y = lanes[w];
      ctx.fillStyle = rgb(T.ink); ctx.font = "650 13px Inter, system-ui, sans-serif"; ctx.fillText((w === "B" ? "Staff " : "Patient ") + w, 24, y + 4);
      ctx.strokeStyle = rgb(T.line); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(Rr, y); ctx.stroke();
    });
    // month ticks
    ctx.fillStyle = rgb(T.muted); ctx.font = "500 11px Inter, system-ui, sans-serif"; ctx.textAlign = "center";
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
    ctx.textAlign = "left"; ctx.font = "500 11.5px Inter, system-ui, sans-serif"; let kx = 420; const ky = 452;
    ctx.fillStyle = rgb(T.pos); ctx.beginPath(); ctx.arc(kx, ky - 4, 5, 0, 7); ctx.fill(); ctx.fillStyle = rgb(T.muted); ctx.fillText("swab: MRSA", kx + 10, ky); kx += 100;
    ctx.beginPath(); ctx.arc(kx, ky - 4, 5, 0, 7); ctx.strokeStyle = rgb(T.muted); ctx.lineWidth = 2; ctx.stroke(); ctx.fillText("swab: no MRSA", kx + 10, ky); kx += 115;
    roundRect(kx - 3, ky - 11, 6, 14, 3); ctx.fillStyle = rgb(T.accent); ctx.fill(); ctx.fillStyle = rgb(T.muted); ctx.fillText("contact day (taller = longer)", kx + 10, ky);
  }

  let last = performance.now(), clock = 0;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now; clock += dt;
    if (S.scene === STORY) {
      updateStory(dt);
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      drawStory(clock);
      drawFade(dt);
      requestAnimationFrame(frame);
      return;
    }
    if (S.playing && (S.scene === 0 || S.scene === 1)) {
      S.playAcc += dt;
      if (S.playAcc > 1.7) { S.playAcc = 0; S.week = (S.week + 1) % D.weeks.length; syncWeekUI(); }
    }
    updateFigures(dt); updateVisitors(dt);
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    drawFloor(clock);
    drawLinks(clock);
    drawTrails();
    const all = figures.concat(visitors).sort((a, b) => a.y - b.y);
    all.forEach((f) => drawFigure(f, clock));
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
    const b = cv.getBoundingClientRect(), x = (ev.clientX - b.left) / b.width * W, y = (ev.clientY - b.top) / b.height * H;
    return G.find((g) => { const r = ROOM[g]; return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }) || null;
  }
  cv.addEventListener("mousemove", (ev) => {
    const g = roomAt(ev); S.hover = g; cv.style.cursor = g ? "pointer" : "default";
    const tip = $("tip");
    if (!g) { tip.hidden = true; return; }
    const r = ROOM[g], b = cv.getBoundingClientRect();
    tip.style.left = ((r.x + r.w / 2) / W * b.width) + "px"; tip.style.top = (r.y / H * b.height + (r.top ? 6 : 0)) + "px";
    if (r.top) tip.style.top = (r.y / H * b.height + 8) + "px";
    tip.innerHTML = tipHtml(g); tip.hidden = false;
    if (r.top) tip.style.transform = "translate(-50%, 8px)"; else tip.style.transform = "";
  });
  cv.addEventListener("mouseleave", () => { S.hover = null; $("tip").hidden = true; });
  cv.addEventListener("click", (ev) => {
    const g = roomAt(ev); if (!g) return;
    if (S.scene === 2) { S.fcWard = g; renderPanel(false); }
  });

  function tipHtml(g) {
    const pp = D.people[g];
    let rows = `<div class="row">People in contact data<b>${pp.patients + pp.staff}</b></div>`;
    if (S.scene <= 2) {
      const wk = S.scene === 2 ? S.fcWeek : S.week, r = weekOf(wk).groups[g];
      rows += r ? `<div class="row">Tested in week ${wk}<b>${r.tested}</b></div><div class="row">MRSA-positive<b>${r.positive} (${pct(r.p)})</b></div>`
               : `<div class="row">Week ${wk}<b>nobody tested</b></div>`;
      if (S.scene === 1) rows += `<div class="row">Time spent inside own group<b>${pct(D.contacts.within_share[g])}</b></div>`;
    } else if (S.scene === 3) {
      const w = D.superspreader.wards.find((s) => s.ward === g);
      rows += `<div class="row">Cut its contacts 50%: days saved<b>${fmt(w.drop)}</b></div><div class="row">Koopman mode weight<b>${pct(w.koopman)}</b></div>`;
    } else {
      rows += `<div class="row">Average MRSA share<b>${pct(meanPrev[g])}</b></div>`;
    }
    return `<h4>${g}</h4>${rows}`;
  }

  // ---------- scenes ----------
  const SCENES = [
    { id: STORY, name: "How it spreads", render: sceneStory, bar: storyBar },
    { id: 0, name: "Hospital", render: sceneHospital, bar: weekBar },
    { id: 1, name: "Contacts", render: sceneContacts, bar: weekBar },
    { id: 2, name: "Forecast", render: sceneForecast, bar: forecastBar },
    { id: 3, name: "Superspreader", render: sceneSuper, bar: () => `<span class="bar-hint">The highlighted room is the one whose contacts matter most. Hover any room for its numbers.</span>` },
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
    S.pos = clamp(i, 0, SCENES.length - 1); S.scene = SCENES[S.pos].id; S.playing = false;
    visitors.length = 0; S.hover = null; $("tip").hidden = true;
    if (S.scene === STORY) { SS.step = 0; SS.acc = 0; SS.since = 0; SS.playing = true; }
    $("legend").hidden = S.scene === STORY;
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
  function forecastBar() {
    const wks = [...new Set(D.forecast.points.map((p) => p.landing_week))].sort((a, b) => a - b);
    return `<span class="bar-label">Week</span><div class="chips">${wks.map((w) => `<button class="chip ${w === S.fcWeek ? "on" : ""}" data-fw="${w}">${w}</button>`).join("")}</div>
      <span class="bar-hint" style="margin-left:auto">Click a room to chart it</span>`;
  }
  function interventionBar() {
    return `<span class="bar-label">Wards</span><div class="chips">${[1, 2].map((k) => `<button class="chip ${k === S.k ? "on" : ""}" data-k="${k}">${k}</button>`).join("")}</div>
      <span class="bar-label" style="margin-left:10px">Contact cut</span><div class="chips">${[0.25, 0.5, 0.75].map((r) => `<button class="chip ${r === S.R ? "on" : ""}" data-r="${r}">${r * 100}%</button>`).join("")}</div>`;
  }
  const playIconPlay = () => `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>`;
  const playIconPause = () => `<svg viewBox="0 0 24 24" width="18" height="18"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>`;
  function wireBar() {
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
    document.querySelectorAll("[data-fw]").forEach((b) => b.onclick = () => { S.fcWeek = +b.dataset.fw; renderBar(); renderPanel(false); });
    document.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => { S.k = +b.dataset.k; renderBar(); renderPanel(false); });
    document.querySelectorAll("[data-r]").forEach((b) => b.onclick = () => { S.R = +b.dataset.r; renderBar(); renderPanel(false); });
  }
  function syncWeekUI() {
    const wk = weekOf(S.week);
    if ($("wkLabel")) $("wkLabel").textContent = `Week ${S.week}`;
    if ($("wkDate")) $("wkDate").textContent = `from Mon ${wk.monday}`;
    if ($("wkSlider")) $("wkSlider").value = S.week;
    const ov = $("ovNow"); if (ov) ov.textContent = pct(overall[S.week]);
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
  function sceneHospital() {
    const valid = overall.filter((v) => v != null), mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    return `<p class="kicker">The whole hospital</p>
      <h2>About ${Math.round(mean * 100)}% of people tested each week carried MRSA.</h2>
      <p>Each room is one ward. <strong>Red figures carry MRSA</strong> and stand at the front, so you can count them. Press play to watch the weeks go by.</p>
      <div class="big-wrap"><span class="big-number" id="ovNow" style="color:var(--pos)">${pct(overall[S.week])}</span><span>tested positive<br>in the week shown</span></div>
      ${sparkline()}
      <p class="fine">Dashed room = few or no swabs that week. Gaps are never filled in.</p>`;
  }

  function sceneContacts() {
    const totalIn = G.reduce((s, g) => s + D.contacts.inside_hours[g], 0);
    const totalBetween = D.contacts.links.reduce((s, l) => s + l.hours, 0) * 2;
    const share = totalIn / (totalIn + totalBetween);
    const top = [...D.contacts.links].sort((a, b) => b.hours - a.hours).slice(0, 3);
    return `<p class="kicker">Who meets whom</p>
      <h2>${Math.round(share * 100)}% of contact time stays inside a ward.</h2>
      <p>The rest happens along a few corridor links. <strong>Staff carrying MRSA leave red footprints</strong> as they walk between wards.</p>
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
      <div class="chart-title">${S.fcWard} <span>click a room to switch</span></div>
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
      if (e.key === "ArrowRight") SS.step < STEPS.length - 1 ? storyGo(SS.step + 1) : go(S.pos + 1);
      else if (SS.step > 0) storyGo(SS.step - 1);
      return;
    }
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
    if (e.key === "f" || e.key === "F") togglePresent();
    if (e.key === "t" || e.key === "T") $("themeBtn").click();
  });
  $("themeBtn").onclick = () => {
    const root = document.documentElement, dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark"; readTokens();
    try { localStorage.setItem("p30-theme", root.dataset.theme); } catch (e) { /* storage unavailable */ }
  };
  try { const t = localStorage.getItem("p30-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* storage unavailable */ }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readTokens);

  $("perFigure").textContent = `Each figure ≈ ${D.people_per_figure} people`;
  readTokens(); resize(); go(0);
  requestAnimationFrame(frame);
})();
