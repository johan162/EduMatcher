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
    ["NYSE", .185, .50, 6.2], ["NASDAQ", .215, .36, 5.4], ["CME", .125, .60, 4.8], ["TSX", .195, .23, 3.8], ["B3", .245, .815, 3.4],
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
    function size() {
      var r = canvas.getBoundingClientRect(); W = r.width; H = r.height;
      canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    size(); window.addEventListener("resize", size);
    var wide = function () { return W > 640; };
    window.addEventListener("pointermove", function (e) { mx = (e.clientX / innerWidth - .5); my = (e.clientY / innerHeight - .5); }, { passive: true });
    function P(i) { var e = EX[i]; return { x: e[1] * W + mx * -14 * (e[3] / 5), y: e[2] * H + my * -10 * (e[3] / 5) }; }
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
          ctx.fillText(e[0], q.x + r + 7, q.y + 4);
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
