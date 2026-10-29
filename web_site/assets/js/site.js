/* EduMatcher site — theme, navigation, reveal, tabs, lightbox, and the live illustrations. No dependencies. */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };
  var rand = function (a, b) { return a + Math.random() * (b - a); };
  var isDark = function () { return root.getAttribute("data-theme") === "dark"; };

  /* ---------- Theme ---------- */
  function setTheme(t, persist) {
    root.setAttribute("data-theme", t);
    if (persist) { try { localStorage.setItem("em-theme", t); } catch (e) {} }
    $$(".theme-toggle").forEach(function (b) { b.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme"); });
    document.dispatchEvent(new CustomEvent("em-theme", { detail: t }));
  }
  $$(".theme-toggle").forEach(function (b) {
    b.addEventListener("click", function () { setTheme(isDark() ? "light" : "dark", true); });
  });
  setTheme(root.getAttribute("data-theme") || "dark", false);
  if (window.matchMedia) {
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (e) {
      var saved = null; try { saved = localStorage.getItem("em-theme"); } catch (x) {}
      if (!saved) setTheme(e.matches ? "dark" : "light", false);
    });
  }

  /* ---------- Mobile menu ---------- */
  var menuBtn = $(".menu-btn"), nav = $(".nav");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var o = nav.classList.toggle("open"); menuBtn.setAttribute("aria-expanded", o);
    });
    $$("a", nav).forEach(function (a) { a.addEventListener("click", function () { nav.classList.remove("open"); }); });
  }

  /* ---------- Reveal on scroll ---------- */
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (es) {
    es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { threshold: 0.12 }) : null;
  $$(".rv, .reveal-group").forEach(function (el) { io ? io.observe(el) : el.classList.add("in"); });

  /* ---------- Counters ---------- */
  function count(el) {
    var to = parseFloat(el.getAttribute("data-count")), dec = (el.getAttribute("data-count").split(".")[1] || "").length;
    var t0 = performance.now(), dur = 1500;
    function f(n) {
      var p = Math.min(1, (n - t0) / dur), e = 1 - Math.pow(1 - p, 3), v = to * e;
      el.textContent = (dec ? v.toFixed(dec) : Math.round(v)).toLocaleString("en-US");
      if (p < 1) requestAnimationFrame(f);
    }
    reduce ? (el.textContent = to.toLocaleString("en-US")) : requestAnimationFrame(f);
  }
  if (io) {
    var cio = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { count(e.target); cio.unobserve(e.target); } }); }, { threshold: 0.5 });
    $$("[data-count]").forEach(function (el) { cio.observe(el); });
  } else { $$("[data-count]").forEach(count); }

  /* ---------- Copy buttons ---------- */
  $$("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = $(btn.getAttribute("data-copy"));
      var txt = target ? target.innerText.replace(/^\$ /gm, "").trim() : "";
      var done = function () { var o = btn.textContent; btn.textContent = "copied"; btn.classList.add("done"); setTimeout(function () { btn.textContent = o; btn.classList.remove("done"); }, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(done, done); else done();
    });
  });

  /* ---------- Tabs ---------- */
  $$("[data-tabs]").forEach(function (group) {
    var tabs = $$("[role=tab]", group), panels = $$(".tabpanel", group.parentNode);
    function show(i) {
      tabs.forEach(function (t, k) { t.setAttribute("aria-selected", k === i); });
      panels.forEach(function (p, k) { p.classList.toggle("active", k === i); });
    }
    tabs.forEach(function (t, i) { t.addEventListener("click", function () { show(i); history.replaceState(null, "", "#" + t.getAttribute("data-id")); }); });
    var h = location.hash.slice(1), idx = tabs.findIndex(function (t) { return t.getAttribute("data-id") === h; });
    show(idx > -1 ? idx : 0);
  });

  /* ---------- Lightbox ---------- */
  var lb = document.createElement("div"); lb.className = "lightbox"; lb.innerHTML = "<img alt=''>"; document.body.appendChild(lb);
  lb.addEventListener("click", function () { lb.classList.remove("open"); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") lb.classList.remove("open"); });
  document.addEventListener("click", function (e) {
    var im = e.target.closest && e.target.closest(".zoomable img");
    if (im) { lb.firstChild.src = im.currentSrc || im.src; lb.firstChild.alt = im.alt; lb.classList.add("open"); }
  });

  /* ---------- Diagram highlight ---------- */
  $$(".diagram[data-hl]").forEach(function (d) {
    $$(".node", d).forEach(function (n) {
      n.addEventListener("mouseenter", function () {
        d.classList.add("hl"); n.classList.add("on");
        (n.getAttribute("data-link") || "").split(" ").forEach(function (id) { var o = id && d.querySelector("#" + id); if (o) o.classList.add("on"); });
      });
      n.addEventListener("mouseleave", function () { d.classList.remove("hl"); $$(".on", d).forEach(function (x) { x.classList.remove("on"); }); });
    });
  });

  /* ---------- Visibility helper for animations ---------- */
  function visible(el, cb) {
    var vis = true;
    if ("IntersectionObserver" in window) new IntersectionObserver(function (es) { vis = es[0].isIntersecting; if (vis) cb.wake && cb.wake(); }).observe(el);
    return function () { return vis && !document.hidden; };
  }

  /* ---------- Exchange network canvas (the book-cover constellation) ---------- */
  var EX = [
    ["NYSE", .140, .555, 5.2], ["NASDAQ", .215, .36, 5.4], ["CME", .125, .60, 4.8], ["TSX", .195, .23, 3.8], ["B3", .245, .815, 3.4],
    ["LSE", .462, .30, 5.8], ["Euronext", .492, .365, 4], ["Eurex", .535, .41, 4.2], ["DFM", .605, .50, 3.2], ["JPX", .825, .36, 5.2],
    ["HKEX", .775, .52, 5.6], ["SGX", .735, .665, 4], ["ASX", .80, .815, 3.6], ["OMX", .50, .20, 3.6], ["NSE", .66, .62, 3.4]
  ];
  var RT = [["NYSE", "LSE", -.26, 1], ["NASDAQ", "Eurex", -.18, 1], ["CME", "Eurex", -.14, 0], ["TSX", "NASDAQ", .18, 0], ["LSE", "Eurex", .12, 0], ["LSE", "Euronext", .08, 0],
    ["LSE", "DFM", .10, 0], ["DFM", "JPX", -.08, 0], ["DFM", "HKEX", -.05, 1], ["Eurex", "JPX", -.22, 1], ["JPX", "HKEX", .18, 0], ["HKEX", "SGX", .12, 0],
    ["SGX", "ASX", .14, 0], ["NYSE", "HKEX", .28, 1], ["NYSE", "B3", .10, 0], ["CME", "LSE", -.20, 0], ["JPX", "ASX", .15, 0], ["OMX", "LSE", .1, 0], ["OMX", "Eurex", -.1, 0],
    ["NSE", "DFM", .1, 0], ["NSE", "SGX", -.1, 0]];

  function startNet(canvas) {
    var ctx = canvas.getContext("2d"), W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var idx = {}; EX.forEach(function (e, i) { idx[e[0]] = i; });
    var pulses = RT.map(function (r) { return { a: idx[r[0]], b: idx[r[1]], c: r[2], major: r[3], t: Math.random(), v: (r[3] ? .0016 : .0009) * rand(.8, 1.5) }; });
    var mx = 0, my = 0, ok = visible(canvas, {});
    /* EX x-fractions are laid out on a 1920 px screen, where the .wrap text column spans 370–1550.
       Stars inside the column scale with it; stars in a gutter keep their distance from the column edge
       (clamped to the screen), so they never drift behind the text. */
    var DW = 1920, DL = 370, DC = 1180, M = 14, BX = [], CL = 0, CR = 0;
    function size() {
      var r = canvas.getBoundingClientRect(); W = r.width; H = r.height;
      canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var cw = Math.min(DC, W - 40); CL = (W - cw) / 2; CR = CL + cw;
      BX = EX.map(function (e) {
        var xd = e[1] * DW;
        if (xd < DL) return Math.max(M, CL - (DL - xd));
        if (xd > DL + DC) return Math.min(W - M, CR + (xd - DL - DC));
        return CL + (xd - DL) / DC * cw;
      });
    }
    size(); window.addEventListener("resize", size);
    var wide = function () { return W > 640; };
    window.addEventListener("pointermove", function (e) { mx = (e.clientX / innerWidth - .5); my = (e.clientY / innerHeight - .5); }, { passive: true });
    function P(i) { var e = EX[i]; return { x: BX[i] + mx * -14 * (e[3] / 5), y: e[2] * H + my * -10 * (e[3] / 5) }; }
    /* a gutter star's label is drawn only where it fits beside the column */
    function labelFits(i, x0, w) { return BX[i] >= CL && BX[i] <= CR || (BX[i] < CL ? x0 + w <= CL - 6 : x0 + w <= W - 4); }
    function ctrl(p, q, c) { return { x: (p.x + q.x) / 2 - (q.y - p.y) * c, y: (p.y + q.y) / 2 + (q.x - p.x) * c }; }
    function bez(p, k, q, t) { var u = 1 - t; return { x: u * u * p.x + 2 * u * t * k.x + t * t * q.x, y: u * u * p.y + 2 * u * t * k.y + t * t * q.y }; }

    function frame() {
      requestAnimationFrame(frame);
      if (!ok()) return;
      var d = isDark();
      var C = d ? { line: "0,170,255", node: "#80e8ff", core: "#ffffff", edge: "#00a8d4", glow: "0,200,255", label: "rgba(200,230,255,.85)", gridA: .042 }
        : { line: "0,100,190", node: "#6fb6ea", core: "#ffffff", edge: "#0a64b0", glow: "0,120,200", label: "rgba(6,40,90,.82)", gridA: .05 };
      ctx.clearRect(0, 0, W, H);
      /* grid */
      ctx.strokeStyle = "rgba(" + (d ? "0,190,255" : "0,90,170") + "," + C.gridA + ")"; ctx.lineWidth = .6;
      for (var x = 0; x < W; x += 36) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (var y = 0; y < H; y += 36) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      /* routes */
      pulses.forEach(function (p) {
        var a = P(p.a), b = P(p.b), k = ctrl(a, b, p.c);
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(k.x, k.y, b.x, b.y);
        ctx.strokeStyle = "rgba(" + C.line + "," + (p.major ? .22 : .12) + ")"; ctx.lineWidth = p.major ? 1.2 : .8;
        ctx.setLineDash(p.major ? [] : [5, 9]); ctx.stroke(); ctx.setLineDash([]);
      });
      /* pulses */
      pulses.forEach(function (p) {
        var a = P(p.a), b = P(p.b), k = ctrl(a, b, p.c), pt = bez(a, k, b, p.t), r = p.major ? 10 : 6.5;
        var g = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, r);
        g.addColorStop(0, d ? "rgba(0,220,255,.95)" : "rgba(0,110,200,.9)"); g.addColorStop(.4, "rgba(" + C.line + ",.3)"); g.addColorStop(1, "rgba(" + C.line + ",0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(pt.x, pt.y, r, 0, 6.3); ctx.fill();
        var t0 = Math.max(0, p.t - .05), p0 = bez(a, k, b, t0), lg = ctx.createLinearGradient(p0.x, p0.y, pt.x, pt.y);
        lg.addColorStop(0, "rgba(" + C.glow + ",0)"); lg.addColorStop(1, "rgba(" + C.glow + (p.major ? ",.6)" : ",.32)"));
        ctx.strokeStyle = lg; ctx.lineWidth = p.major ? 1.8 : 1.2; ctx.beginPath(); ctx.moveTo(p0.x, p0.y); ctx.lineTo(pt.x, pt.y); ctx.stroke();
        if (!reduce) { p.t += p.v; if (p.t > 1) p.t = 0; }
      });
      /* nodes */
      var tt = performance.now() / 1000;
      EX.forEach(function (e, i) {
        var q = P(i), r = e[3], pulse = 1 + (reduce ? 0 : Math.sin(tt * 1.6 + i) * .08);
        var o = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, r * 4.6 * pulse);
        o.addColorStop(0, "rgba(" + C.glow + ",.24)"); o.addColorStop(1, "rgba(" + C.glow + ",0)");
        ctx.fillStyle = o; ctx.beginPath(); ctx.arc(q.x, q.y, r * 4.6 * pulse, 0, 6.3); ctx.fill();
        ctx.beginPath(); ctx.arc(q.x, q.y, r + 2.5, 0, 6.3); ctx.strokeStyle = "rgba(" + C.glow + ",.4)"; ctx.lineWidth = .8; ctx.stroke();
        var dot = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, r);
        dot.addColorStop(0, C.core); dot.addColorStop(.45, C.node); dot.addColorStop(1, C.edge);
        ctx.fillStyle = dot; ctx.beginPath(); ctx.arc(q.x, q.y, r, 0, 6.3); ctx.fill();
        if (wide()) {
          ctx.font = "500 " + Math.max(11, Math.round(W * .0105)) + "px 'DM Mono', monospace"; ctx.fillStyle = C.label;
          if (labelFits(i, q.x + r + 7, ctx.measureText(e[0]).width)) ctx.fillText(e[0], q.x + r + 7, q.y + 4);
        }
      });
    }
    frame();
  }
  $$("canvas.net").forEach(startNet);

  /* ---------- Live order book ladder ---------- */
  var lad = $("#ladder");
  if (lad) {
    var tick = .01, mid = 150.32, rowsEl = $("#lad-rows"), tapeEl = $("#lad-tape"), lastEl = $("#lad-last"), chgEl = $("#lad-chg"), open = mid, N = 6;
    var bids = [], asks = [];
    function seed() { for (var i = 0; i < N; i++) { bids[i] = Math.round(rand(2, 12)) * 100; asks[i] = Math.round(rand(2, 12)) * 100; } }
    seed();
    function fmt(n) { return n.toLocaleString("en-US"); }
    function render() {
      var bb = +(mid - tick / 2).toFixed(2), ba = +(mid + tick / 2).toFixed(2), mx = Math.max.apply(null, bids.concat(asks)), h = "";
      h = "";
      for (var a = N - 1; a >= 0; a--) h += '<div class="row"><div class="bid"></div><div class="px down">' + (ba + a * tick).toFixed(2) + '</div><div class="ask"><i class="bar" style="width:' + (asks[a] / mx * 100) + '%"></i><span>' + fmt(asks[a]) + "</span></div></div>";
      h += '<div class="row mid"><div class="bid"></div><div class="px"></div><div class="ask"></div></div>';
      for (var b = 0; b < N; b++) h += '<div class="row"><div class="bid"><i class="bar" style="width:' + (bids[b] / mx * 100) + '%"></i><span>' + fmt(bids[b]) + '</span></div><div class="px up">' + (bb - b * tick).toFixed(2) + '</div><div class="ask"></div></div>';
      rowsEl.innerHTML = h;
      lastEl.textContent = mid.toFixed(2);
      var c = mid - open; chgEl.textContent = (c >= 0 ? "+" : "") + c.toFixed(2) + "  " + (c >= 0 ? "+" : "") + (c / open * 100).toFixed(2) + "%"; chgEl.className = c >= 0 ? "up" : "down";
    }
    function trade() {
      var buy = Math.random() > .5, q = Math.round(rand(1, 9)) * 25, px = buy ? mid + tick / 2 : mid - tick / 2;
      if (buy) { asks[0] -= q; } else { bids[0] -= q; }
      var d = document.createElement("div");
      d.innerHTML = '<span class="' + (buy ? "up" : "down") + '">' + (buy ? "BUY " : "SELL") + "</span><span>" + px.toFixed(2) + "</span><span>" + q + "</span><span>" + new Date().toTimeString().slice(0, 8) + "</span>";
      tapeEl.insertBefore(d, tapeEl.firstChild); while (tapeEl.children.length > 5) tapeEl.removeChild(tapeEl.lastChild);
      if (asks[0] <= 0 || bids[0] <= 0) {
        if (asks[0] <= 0) { mid = +(mid + tick).toFixed(2); asks.shift(); asks.push(Math.round(rand(2, 12)) * 100); bids.unshift(Math.round(rand(2, 8)) * 100); bids.pop(); }
        else { mid = +(mid - tick).toFixed(2); bids.shift(); bids.push(Math.round(rand(2, 12)) * 100); asks.unshift(Math.round(rand(2, 8)) * 100); asks.pop(); }
      }
    }
    function churn() {
      var i = Math.floor(rand(1, N)), side = Math.random() > .5 ? bids : asks;
      side[i] = Math.max(100, side[i] + Math.round(rand(-4, 5)) * 100);
      side[0] = Math.max(100, side[0] + Math.round(rand(0, 3)) * 25);
    }
    render();
    var okL = visible(lad, {});
    if (!reduce) setInterval(function () { if (!okL()) return; churn(); if (Math.random() > .35) trade(); render(); }, 650);
  }

  /* ---------- Order-book debugger: the deep-dive chapter's worked example, frame by frame ---------- */
  var obd = $("#obd");
  if (obd) {
    var OB = { a1: [10010, "ask"], a2: [10010, "ask"], a3: [10020, "ask"], b1: [10000, "bid"] }, OBK = { a1: 1, a2: 2, a3: 3 };
    var MOD = "&lt;module&gt;", SW = [MOD, "process", "_match_limit", "_sweep"];
    var Q0 = { a1: 300, a2: 200, a3: 500, b1: 400 }, L0 = { 10020: 500, 10010: 500, 10000: 400 };
    /* each step lists only what differs from the previous one */
    var STEPS = [
      { inc: null, q: Q0, gone: [], dead: [], heap: [["a1", 1], ["a2", 1], ["a3", 1]], lvl: L0, hot: null, stack: [], line: null, loc: [], tr: 0,
        cap: "The starting book: three asks and one bid. Every heap entry carries the key <code>(price, arrival_seq)</code> (bids store <code>−price</code>), so <code>heap[0]</code> is always the best price and, among equal prices, the oldest order." },
      { inc: 400, stack: [MOD], line: ["book_lab.py", "trades, events = book.process(buy)"], loc: [["buy.side", "BUY"], ["buy.price_ticks", "10010"], ["buy.quantity", "400"]],
        cap: "Breakpoint hit. A <code>BUY LIMIT 400 @ 100.10</code> from GW3 is about to enter the book. Its limit reaches the best ask, so it will trade. <i>Step Into</i>." },
      { stack: [MOD, "process"], line: ["process", "self._match_limit(order, trades, events, now)"], loc: [["order.order_type", "LIMIT"], ["match", "True"], ["trades", "[]"]],
        cap: "<code>process()</code> is the only way into the book. It picks the matcher for the order type; for LIMIT that is <code>_match_limit</code>, which sweeps the opposite side, the <code>_asks</code> heap, with <code>price_limit=10010</code>." },
      { stack: SW, line: ["_sweep", "best = _peek(opposite_heap)"], hot: "a1", loc: [["aggressor.remaining_qty", "400"], ["best", "a1"], ["best_price", "10010"]],
        cap: "<code>_sweep</code> asks <code>_peek</code> for the best live ask: <b>a1</b>. Its key <code>(10010, 1)</code> beats a2's <code>(10010, 2)</code> on the second element. Time priority is nothing more than <code>arrival_seq</code>." },
      { line: ["_sweep", "fill_qty = min(aggressor.remaining_qty, _passive_avail)"], loc: [["aggressor.remaining_qty", "400"], ["_passive_avail", "300"], ["fill_qty", "300"]],
        cap: "Price check: 100.10 is within the limit. Different gateways, so self-match prevention stays out of it. The fill is the smaller quantity: <code>min(400, 300) = 300</code>." },
      { stack: SW.concat("_apply_fill"), line: ["_apply_fill", "trades.append(trade)"], inc: 100, q: { a1: 0, a2: 200, a3: 500, b1: 400 }, dead: ["a1"], lvl: { 10020: 500, 10010: 200, 10000: 400 }, tr: 1,
        loc: [["trade", "300 @ 10010"], ["aggressor", "PARTIAL 100"], ["passive", "a1 FILLED"]],
        cap: "<code>_apply_fill</code> is where every trade is born. It prints at the <b>resting</b> order's price, then reduces both orders and the level index: <code>_ask_qty[10010]</code> 500 → 200." },
      { stack: SW.concat("_apply_fill", "_purge_from_indexes"), line: ["_purge_from_indexes", "entry.valid = False"], gone: ["a1"], dead: [], heap: [["a1", 0], ["a2", 1], ["a3", 1]], hot: null,
        loc: [["order", "a1"], ["entry.valid", "False"], ["len(_asks)", "3"]],
        cap: "a1 leaves through the single exit door, <code>_purge_from_indexes</code>. Its heap entry is not removed, only flagged <code>valid=False</code>. That is lazy deletion: O(1) now, cleaned up later." },
      { stack: SW.concat("_peek"), line: ["_peek", "heapq.heappop(heap)"], heap: [["a2", 1], ["a3", 1]], hot: "a2", loc: [["popped", "a1 · valid=False"], ["returns", "a2"], ["len(_asks)", "2"]],
        cap: "The next pass. <code>_peek</code> finds a dead entry on top, pops it, and returns <b>a2</b> without popping it. Garbage is thrown away only when it reaches the top of the heap." },
      { stack: SW.concat("_apply_fill"), line: ["_apply_fill", "trades.append(trade)"], inc: 0, q: { a1: 0, a2: 100, a3: 500, b1: 400 }, lvl: { 10020: 500, 10010: 100, 10000: 400 }, tr: 2,
        loc: [["fill_qty", "100"], ["aggressor", "FILLED 0"], ["passive", "a2 PARTIAL 100"]],
        cap: "<code>min(100, 200) = 100</code>: a second trade, 100 @ 100.10, and the aggressor is FILLED. a2 keeps 100 and its place at the front of the queue. A partial fill never costs priority." },
      { stack: [MOD, "process"], line: ["process", "if trades and self._has_stops and _cascade_stops:"], hot: null, loc: [["len(trades)", "2"], ["len(events)", "4"], ["_has_stops", "False"]],
        cap: "<code>remaining_qty == 0</code> ends the loop, so <code>_match_limit</code> has nothing to <code>_rest</code>. No stops are armed, so there is no cascade. <code>process</code> returns <code>(trades, events)</code> to the engine." }
    ];
    for (var si = 1; si < STEPS.length; si++) for (var sk in STEPS[si - 1]) if (!(sk in STEPS[si])) STEPS[si][sk] = STEPS[si - 1][sk];
    var TR = ["300", "100"], cur = 0, playing = !reduce, timer = null, okO = visible(obd, {});
    var obPx = function (t) { return (t / 100).toFixed(2); };
    function obdRender() {
      var s = STEPS[cur], prev = STEPS[cur - 1] || s, h = "";
      $("#obd-n").textContent = "step " + (cur + 1) + " / " + STEPS.length;
      var inc = $("#obd-in");
      inc.className = "obd-in" + (s.inc === null ? "" : " on");
      inc.innerHTML = s.inc === null ? "<span>waiting for an incoming order…</span>"
        : "<span><b>BUY</b> LIMIT 400 @ 100.10 · GW3</span><span>remaining <b>" + s.inc + "</b>" + (s.inc ? "" : " · FILLED") + "</span>";
      [[10020, "ask"], [10010, "ask"], null, [10000, "bid"]].forEach(function (lv) {
        if (!lv) { h += '<div class="obd-row mid"></div>'; return; }
        var chips = Object.keys(OB).filter(function (id) { return OB[id][0] === lv[0] && s.gone.indexOf(id) < 0; }).map(function (id) {
          var cls = s.dead.indexOf(id) > -1 ? " dead" : id === s.hot ? " hot" : "";
          return '<span class="obd-o' + cls + '">' + id + " <i>" + s.q[id] + "</i></span>";
        }).join("");
        h += '<div class="obd-row ' + lv[1] + '"><span class="lq' + (s.lvl[lv[0]] !== prev.lvl[lv[0]] ? " chg" : "") + '">' + s.lvl[lv[0]] + '</span><span class="px">' + obPx(lv[0]) + '</span><div class="obd-q">' + chips + "</div></div>";
      });
      $("#obd-book").innerHTML = h;
      $("#obd-heap").innerHTML = '<span class="k">_asks:</span> [' + s.heap.map(function (e) {
        var cls = !e[1] ? " dead" : e[0] === s.hot ? " hot" : "";
        return '<span class="e' + cls + '">((' + OB[e[0]][0] + ", " + OBK[e[0]] + "), " + e[0] + (e[1] ? "" : ", valid=False") + ")</span>";
      }).join(", ") + ']<br><span class="k">_bids:</span> [<span class="e">((-10000, 4), b1)</span>]';
      $("#obd-stack").innerHTML = s.stack.length ? s.stack.map(function (f, i) { return '<li class="' + (i === s.stack.length - 1 ? "top" : "") + '">' + f + "</li>"; }).reverse().join("") : '<li>(not running)</li>';
      var pl = {}; prev.loc.forEach(function (kv) { pl[kv[0]] = kv[1]; });
      $("#obd-loc").innerHTML = s.loc.map(function (kv) { return "<dt>" + kv[0] + '</dt><dd class="' + (kv[0] in pl && pl[kv[0]] !== kv[1] ? "chg" : "") + '">' + kv[1] + "</dd>"; }).join("");
      $("#obd-line").innerHTML = s.line ? '<span class="fn">▶ ' + s.line[0] + "  </span>" + s.line[1] : '<span class="fn">▶ —</span>';
      $("#obd-cap").innerHTML = s.cap;
      $("#obd-tape").innerHTML = TR.slice(0, s.tr).reverse().map(function (q) { return '<div><span class="up">TRADE</span> ' + q + " @ 100.10</div>"; }).join("");
    }
    function obdGo(i) { cur = (i + STEPS.length) % STEPS.length; obdRender(); }
    function obdTick() {
      clearTimeout(timer);
      if (!playing) return;
      timer = setTimeout(function () { if (okO()) obdGo(cur + 1); obdTick(); }, cur === STEPS.length - 1 ? 7000 : 4200);
    }
    function obdPlay(on) {
      playing = on;
      var b = $("[data-act=play]", obd); b.textContent = on ? "❚❚" : "▶"; b.setAttribute("aria-label", on ? "Pause" : "Play");
      obdTick();
    }
    $$(".obd-ctl button", obd).forEach(function (b) {
      b.addEventListener("click", function () {
        var a = b.getAttribute("data-act");
        if (a === "play") { obdPlay(!playing); return; }
        obdPlay(false); obdGo(cur + (a === "next" ? 1 : -1));
      });
    });
    obdRender(); obdPlay(playing);
  }

  /* ---------- Price discovery chart: price chases a hidden true value ---------- */
  var pd = $("#pdchart");
  if (pd) {
    var cx = pd.getContext("2d"), dpr2 = Math.min(window.devicePixelRatio || 1, 2), PW, PH, pts = [], N2 = 220, tv = 100, px = 100, nxt = 45, okP = visible(pd, {}), news = [];
    function psize() { var r = pd.getBoundingClientRect(); PW = r.width; PH = r.height; pd.width = PW * dpr2; pd.height = PH * dpr2; cx.setTransform(dpr2, 0, 0, dpr2, 0, 0); }
    psize(); window.addEventListener("resize", psize);
    function step() {
      nxt--; tv += rand(-.12, .12);
      if (nxt <= 0) { var j = (Math.random() > .5 ? 1 : -1) * rand(2.2, 4.5); tv += j; news.push({ i: N2 - 1, up: j > 0 }); nxt = Math.round(rand(60, 100)); }
      px += (tv - px) * .05 + rand(-.45, .45);
      pts.push({ p: px, t: tv }); if (pts.length > N2) { pts.shift(); news.forEach(function (n) { n.i--; }); news = news.filter(function (n) { return n.i > 0; }); }
    }
    for (var s = 0; s < N2; s++) step();
    function draw() {
      requestAnimationFrame(draw); if (!okP()) return;
      var d = isDark(), up = d ? "#00e676" : "#08894a", dn = d ? "#ff3d5a" : "#d02040", am = d ? "#ffb020" : "#b86e00", gr = d ? "rgba(0,190,255,.08)" : "rgba(0,90,170,.1)", tx = d ? "#8199ba" : "#566d8c";
      if (!reduce) step();
      var lo = Infinity, hi = -Infinity; pts.forEach(function (q) { lo = Math.min(lo, q.p, q.t); hi = Math.max(hi, q.p, q.t); }); lo -= 1; hi += 1;
      var X = function (i) { return 8 + (PW - 70) * i / (N2 - 1); }, Y = function (val) { return 10 + (PH - 24) * (1 - (val - lo) / (hi - lo)); };
      cx.clearRect(0, 0, PW, PH); cx.strokeStyle = gr; cx.lineWidth = 1;
      for (var g = 0; g < 5; g++) { var yy = 10 + (PH - 24) * g / 4; cx.beginPath(); cx.moveTo(0, yy); cx.lineTo(PW - 56, yy); cx.stroke(); cx.fillStyle = tx; cx.font = "11px 'DM Mono',monospace"; cx.fillText((hi - (hi - lo) * g / 4).toFixed(1), PW - 50, yy + 4); }
      news.forEach(function (n) { var x = X(n.i); cx.strokeStyle = n.up ? up : dn; cx.globalAlpha = .45; cx.setLineDash([3, 4]); cx.beginPath(); cx.moveTo(x, 8); cx.lineTo(x, PH - 14); cx.stroke(); cx.setLineDash([]); cx.globalAlpha = 1; cx.fillStyle = n.up ? up : dn; cx.font = "10px 'DM Mono',monospace"; cx.fillText("NEWS " + (n.up ? "+" : "−"), x - 18, 18); });
      cx.strokeStyle = am; cx.lineWidth = 1.6; cx.setLineDash([6, 5]); cx.beginPath(); pts.forEach(function (q, i) { i ? cx.lineTo(X(i), Y(q.t)) : cx.moveTo(X(i), Y(q.t)); }); cx.stroke(); cx.setLineDash([]);
      cx.strokeStyle = d ? "#00d4ff" : "#0072b0"; cx.lineWidth = 2.2; cx.beginPath(); pts.forEach(function (q, i) { i ? cx.lineTo(X(i), Y(q.p)) : cx.moveTo(X(i), Y(q.p)); }); cx.stroke();
      var l = pts[pts.length - 1]; cx.fillStyle = d ? "#00d4ff" : "#0072b0"; cx.beginPath(); cx.arc(X(N2 - 1), Y(l.p), 4, 0, 6.3); cx.fill();
    }
    draw();
  }

  /* ---------- Agent swarm ---------- */
  var sw = $("#swarm");
  if (sw) {
    var cells = []; for (var i = 0; i < 100; i++) { var c = document.createElement("i"); sw.appendChild(c); cells.push(c); }
    var okS = visible(sw, {});
    function flip() { if (!okS()) return; for (var k = 0; k < 7; k++) { var c = cells[Math.floor(Math.random() * 100)], r = Math.random(); c.className = r < .36 ? "buy" : r < .72 ? "sell" : ""; } }
    for (var z = 0; z < 20; z++) flip();
    if (!reduce) setInterval(flip, 260);
  }

  /* ---------- Header ticker tape (illustrative) ---------- */
  var tape = $("#tape");
  if (tape) {
    var syms = [["EDX100", 4210.4], ["AAPL", 182.4], ["MSFT", 330.1], ["NVDA", 287.5], ["TSLA", 90.4], ["AMZN", 248.7], ["GOOGL", 114.4], ["META", 66.8], ["NFLX", 162.1], ["JPM", 155.2], ["XOM", 213.5], ["WMT", 169.9], ["V", 100.1], ["UPS", 99.4], ["VZ", 246.4]];
    var h = ""; for (var rep = 0; rep < 2; rep++) syms.forEach(function (s) {
      var ch = (Math.sin(s[1]) * 1.4), u = ch >= 0;
      h += '<span class="t"><b>' + s[0] + "</b>" + s[1].toFixed(2) + ' <span class="' + (u ? "up" : "down") + '">' + (u ? "▲ +" : "▼ ") + ch.toFixed(2) + "%</span></span>";
    });
    tape.innerHTML = h;
  }
})();
