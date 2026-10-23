/* Adds the web-site home link + menu to the Material header and keeps the
   light/dark choice in sync with the rest of the site (localStorage "em-theme"). */
(function () {
  "use strict";
  function root() {
    var cfg = document.getElementById("__config"), base = "";
    try { base = JSON.parse(cfg.textContent).base; } catch (e) {}
    return new URL(base + "/../", location.href).pathname.replace(/\/+$/, "/");
  }
  function addNav() {
    var inner = document.querySelector(".md-header__inner");
    if (!inner || inner.querySelector(".em-home")) return;
    var r = root();
    var a = document.createElement("a");
    a.className = "em-home"; a.href = r + "index.html"; a.setAttribute("aria-label", "EduMatcher home");
    a.innerHTML = "EDU<em>MATCHER</em>";
    var nav = document.createElement("nav"); nav.className = "em-sitenav"; nav.setAttribute("aria-label", "Site");
    [["Platform", "platform.html"], ["Applications", "apps.html"], ["Learn", "learn.html"], ["Library", "docs.html"], ["Download", "download.html"]].forEach(function (l) {
      var x = document.createElement("a"); x.href = r + l[1]; x.textContent = l[0]; nav.appendChild(x);
    });
    var ver = document.createElement("span"); ver.className = "em-ver"; ver.textContent = "DOCS";
    inner.insertBefore(a, inner.firstChild);
    var title = inner.querySelector(".md-header__title");
    inner.insertBefore(nav, title);
    inner.insertBefore(ver, nav);
  }
  function sync() {
    var s = document.body.getAttribute("data-md-color-scheme");
    if (s) { try { localStorage.setItem("em-theme", s === "slate" ? "dark" : "light"); } catch (e) {} }
  }
  function init() {
    addNav(); sync();
    new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
