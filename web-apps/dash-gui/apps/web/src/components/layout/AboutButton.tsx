/**
 * The About glyph left of the MarketSim wordmark and the popup it opens:
 * what MarketSim is, version, licence (MIT), copyright and the project site.
 *
 * Self-contained on purpose — inline styles and an inline SVG, no Tailwind
 * tokens or icon library — so the same file serves every web GUI (book,
 * clearing, config, dash, log, terminal, trader). Edit it in one app, copy it
 * to the others and run each app's Prettier on the copy.
 *
 * The popup is always dark: its animated background is a small version of the
 * project homepage's hero (a grid, glowing exchange nodes, curved routes with
 * travelling pulses), which only reads well on navy.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

const SITE_URL = "https://johan162.github.io/market-sim/index.html";
const COPYRIGHT = "Copyright © 2026 Johan Persson";

const MIT_TEXT = `Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.`;

const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";
const SANS = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

/** The glyph's light/dark looks and the hover/focus states inline styles cannot express. */
const CSS = `
.ms-about-btn {
  border: 1px solid rgba(0, 150, 220, .55);
  background: radial-gradient(circle at 32% 26%, rgba(255, 255, 255, .6), rgba(0, 170, 240, .2) 55%, rgba(0, 110, 200, .12));
  box-shadow: 0 0 5px rgba(0, 170, 240, .3);
  color: #0a8fd0;
  transition: box-shadow .2s, border .2s, transform .2s;
}
.dark .ms-about-btn {
  border: 1px solid rgba(0, 200, 255, .5);
  background: radial-gradient(circle at 32% 26%, rgba(150, 235, 255, .4), rgba(0, 170, 240, .2) 55%, rgba(0, 90, 170, .18));
  box-shadow: 0 0 6px rgba(0, 190, 255, .3);
  color: #8fe6ff;
}
.ms-about-btn:hover, .ms-about-btn:focus-visible {
  border: 1px solid rgba(0, 190, 255, .9);
  box-shadow: 0 0 0 1px rgba(0, 190, 255, .25), 0 0 10px rgba(0, 180, 255, .55);
  transform: scale(1.06);
  outline: none;
}
.ms-about-link { color: #00d4ff; box-shadow: inset 0 -1px 0 rgba(0, 212, 255, .35); }
.ms-about-link:hover { box-shadow: inset 0 -1px 0 #00d4ff; }
.ms-about-close:hover, .ms-about-close:focus-visible { color: #e6f1ff; background: rgba(0, 210, 255, .12); outline: none; }
.ms-about-details summary { cursor: pointer; color: #8199ba; }
.ms-about-details summary:hover { color: #b9cde8; }
`;

export function AboutButton({ app, version }: { app: string; version: string }) {
  const [open, setOpen] = useState(false);
  // Stable, so a top bar re-rendering every second (a clock) does not re-run the dialog's effect.
  const close = useCallback(() => setOpen(false), []);
  return (
    <>
      <style>{CSS}</style>
      <button
        type="button"
        className="ms-about-btn"
        onClick={() => setOpen(true)}
        aria-label="About MarketSim"
        title="About MarketSim"
        style={{
          alignSelf: "center",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 20,
          height: 20,
          padding: 0,
          flexShrink: 0,
          borderRadius: "50%",
          cursor: "pointer",
        }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="6.5" r="2" fill="currentColor" />
          <path d="M12 11v8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </button>
      {open && createPortal(<AboutDialog app={app} version={version} onClose={close} />, document.body)}
    </>
  );
}

function AboutDialog({ app, version, onClose }: { app: string; version: string; onClose: () => void }) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        background: "rgba(2, 8, 20, .62)",
        backdropFilter: "blur(3px)",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "relative",
          overflowX: "hidden",
          width: "100%",
          maxWidth: 460,
          maxHeight: "calc(100vh - 32px)",
          overflowY: "auto",
          borderRadius: 14,
          border: "1px solid rgba(0, 210, 255, .28)",
          background: "linear-gradient(160deg, #04132a 0%, #020c1b 70%)",
          boxShadow: "0 24px 60px -20px rgba(0,0,0,.8), 0 0 40px -10px rgba(0, 170, 255, .35)",
          color: "#e6f1ff",
          fontFamily: SANS,
          fontSize: 13.5,
          lineHeight: 1.55,
          textAlign: "left",
        }}
      >
        <NetBackground />
        {/* Fade the network out behind the text so it stays readable. */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background:
              "linear-gradient(180deg, rgba(2,12,27,0) 0%, rgba(2,12,27,.55) 38%, rgba(2,12,27,.88) 70%)",
          }}
        />

        <div style={{ position: "relative", padding: "26px 26px 22px" }}>
          <button
            ref={closeRef}
            type="button"
            className="ms-about-close"
            onClick={onClose}
            aria-label="Close"
            style={{
              position: "absolute",
              top: 10,
              right: 10,
              width: 28,
              height: 28,
              border: "none",
              borderRadius: 6,
              background: "transparent",
              color: "#8199ba",
              fontSize: 20,
              lineHeight: 1,
              cursor: "pointer",
            }}
          >
            ×
          </button>

          <div
            style={{
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "#00d4ff",
            }}
          >
            Market microstructure simulator
          </div>
          <h2
            id={titleId}
            style={{
              margin: "6px 0 2px",
              fontFamily: MONO,
              fontSize: 30,
              fontWeight: 700,
              color: "#ffffff",
              textShadow: "0 0 24px rgba(0, 212, 255, .45)",
            }}
          >
            MarketSim
          </h2>
          <div style={{ fontFamily: MONO, fontSize: 12, color: "#8199ba" }}>
            {app} · v{version}
          </div>

          <p style={{ margin: "18px 0 0", color: "#b9cde8" }}>
            MarketSim is a simulated stock market: order books, matching, auctions, market data and clearing,
            running live with a market maker and AI traders. It accompanies the book{" "}
            <em style={{ color: "#e6f1ff" }}>Exchange Concepts: An Introduction</em>, so every idea in the
            book can be watched and tried on a working exchange.
          </p>

          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "6px 16px",
              margin: "18px 0 0",
              padding: "12px 14px",
              borderRadius: 10,
              border: "1px solid rgba(0, 210, 255, .16)",
              background: "rgba(8, 30, 60, .55)",
              fontSize: 12.5,
            }}
          >
            <dt style={{ color: "#8199ba" }}>Version</dt>
            <dd style={{ margin: 0, fontFamily: MONO }}>{version}</dd>
            <dt style={{ color: "#8199ba" }}>License</dt>
            <dd style={{ margin: 0 }}>MIT</dd>
            <dt style={{ color: "#8199ba" }}>Copyright</dt>
            <dd style={{ margin: 0 }}>{COPYRIGHT}</dd>
            <dt style={{ color: "#8199ba" }}>Website</dt>
            <dd style={{ margin: 0, overflowWrap: "anywhere" }}>
              <a
                className="ms-about-link"
                href={SITE_URL}
                target="_blank"
                rel="noopener noreferrer"
                style={{ textDecoration: "none" }}
              >
                johan162.github.io/market-sim
              </a>
            </dd>
          </dl>

          <p style={{ margin: "14px 0 0", fontSize: 12, color: "#8199ba" }}>
            Free to use, copy, modify and distribute under the MIT License. Provided “as is”, without warranty
            of any kind.
          </p>
          <details className="ms-about-details" style={{ marginTop: 8, fontSize: 12 }}>
            <summary>Full license text</summary>
            <div
              style={{
                marginTop: 8,
                maxHeight: 160,
                overflowY: "auto",
                padding: "10px 12px",
                borderRadius: 8,
                background: "rgba(3, 18, 37, .9)",
                border: "1px solid rgba(0, 210, 255, .12)",
                color: "#b9cde8",
                fontFamily: MONO,
                fontSize: 11,
                whiteSpace: "pre-wrap",
              }}
            >
              {`MIT License\n\n${COPYRIGHT}\n\n${MIT_TEXT}`}
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}

/** Exchange nodes as [x, y, radius], fractions of the card; routes as [from, to, curvature, major]. */
const NODES: [number, number, number][] = [
  [0.1, 0.18, 3.2],
  [0.34, 0.08, 2.4],
  [0.58, 0.22, 3.6],
  [0.86, 0.1, 2.6],
  [0.74, 0.42, 2.2],
  [0.22, 0.44, 2.4],
  [0.94, 0.34, 2],
];
const ROUTES: [number, number, number, boolean][] = [
  [0, 2, 0.18, true],
  [2, 3, -0.2, true],
  [1, 4, 0.22, false],
  [5, 2, -0.16, false],
  [0, 1, -0.25, false],
  [3, 6, 0.3, false],
  [4, 6, -0.2, true],
  [5, 4, 0.12, false],
];

/** The homepage hero, small: grid, routes, travelling pulses and softly breathing nodes. */
function NetBackground() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0;
    let h = 0;
    const size = () => {
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();

    const pulses = ROUTES.map(([a, b, c, major]) => ({
      a,
      b,
      c,
      major,
      t: Math.random(),
      v: (major ? 0.0035 : 0.0022) * (0.8 + Math.random() * 0.6),
    }));
    const at = (i: number) => {
      const [x, y] = NODES[i] ?? [0, 0];
      return { x: x * w, y: y * h };
    };
    const ctrl = (p: { x: number; y: number }, q: { x: number; y: number }, c: number) => ({
      x: (p.x + q.x) / 2 - (q.y - p.y) * c,
      y: (p.y + q.y) / 2 + (q.x - p.x) * c,
    });

    let raf = 0;
    const frame = () => {
      // The card grows when the licence text is expanded.
      if (canvas.clientWidth !== w || canvas.clientHeight !== h) size();
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(0,190,255,.05)";
      ctx.lineWidth = 0.6;
      for (let x = 0; x < w; x += 24) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += 24) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      for (const p of pulses) {
        const a = at(p.a);
        const b = at(p.b);
        const k = ctrl(a, b, p.c);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.quadraticCurveTo(k.x, k.y, b.x, b.y);
        ctx.strokeStyle = `rgba(0,170,255,${p.major ? 0.24 : 0.13})`;
        ctx.lineWidth = p.major ? 1.1 : 0.8;
        ctx.setLineDash(p.major ? [] : [4, 7]);
        ctx.stroke();
        ctx.setLineDash([]);
        const u = 1 - p.t;
        const px = u * u * a.x + 2 * u * p.t * k.x + p.t * p.t * b.x;
        const py = u * u * a.y + 2 * u * p.t * k.y + p.t * p.t * b.y;
        const r = p.major ? 8 : 5.5;
        const g = ctx.createRadialGradient(px, py, 0, px, py, r);
        g.addColorStop(0, "rgba(0,220,255,.9)");
        g.addColorStop(0.4, "rgba(0,170,255,.28)");
        g.addColorStop(1, "rgba(0,170,255,0)");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fill();
        if (!reduce) p.t = (p.t + p.v) % 1;
      }
      const tt = performance.now() / 1000;
      NODES.forEach(([, , rad], i) => {
        const q = at(i);
        const s = 1 + (reduce ? 0 : Math.sin(tt * 1.6 + i) * 0.1);
        const o = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, rad * 4.6 * s);
        o.addColorStop(0, "rgba(0,200,255,.26)");
        o.addColorStop(1, "rgba(0,200,255,0)");
        ctx.fillStyle = o;
        ctx.beginPath();
        ctx.arc(q.x, q.y, rad * 4.6 * s, 0, Math.PI * 2);
        ctx.fill();
        const dot = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, rad);
        dot.addColorStop(0, "#ffffff");
        dot.addColorStop(0.45, "#80e8ff");
        dot.addColorStop(1, "#00a8d4");
        ctx.fillStyle = dot;
        ctx.beginPath();
        ctx.arc(q.x, q.y, rad, 0, Math.PI * 2);
        ctx.fill();
      });
      if (!reduce) raf = requestAnimationFrame(frame);
    };
    frame();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
    />
  );
}
