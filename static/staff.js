/* BioSpine staff analytics helpers (charts, tabs, heat-map, light/dark). Used only on /staff/analytics/ pages. */
(function () {
  "use strict";
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem("bs_staff_theme"); } catch (e) {}
  root.setAttribute("data-theme", saved === "light" ? "light" : "dark");

  var BS = window.BS = {};
  var css = function (n) { return getComputedStyle(root).getPropertyValue(n).trim(); };
  BS.c = { blue: "#38bdf8", green: "#34d399", amber: "#fbbf24", red: "#f87171", violet: "#a78bfa", pink: "#f472b6", slate: "#64748b" };
  BS.json = function (id) { var el = document.getElementById(id); if (!el) return null; try { return JSON.parse(el.textContent); } catch (e) { return null; } };

  BS.chart = function (id, type, data, title, extra) {
    var el = document.getElementById(id);
    if (!el) return null;
    if (typeof Chart === "undefined") { el.insertAdjacentHTML("afterend", '<div class="note">Charts need an internet connection (Chart.js could not load).</div>'); return null; }
    Chart.defaults.color = css("--mut"); Chart.defaults.borderColor = css("--line");
    var opts = { responsive: true, maintainAspectRatio: true, plugins: { title: { display: !!title, text: title, color: css("--txt") }, legend: { labels: { boxWidth: 12 } } } };
    if (extra) for (var k in extra) { if (k === "plugins") { for (var p in extra.plugins) opts.plugins[p] = extra.plugins[p]; } else opts[k] = extra[k]; }
    return new Chart(el, { type: type, data: data, options: opts });
  };
  BS.right = function (min, max) { return { position: "right", min: min, max: max, grid: { drawOnChartArea: false } }; };

  /* 7 x 24 heat map (rows Mon..Sun). Cells are shaded by value. */
  BS.heat = function (id, grid, unit) {
    var el = document.getElementById(id);
    if (!el || !grid) return;
    var max = 0; grid.forEach(function (r) { r.forEach(function (v) { if (v > max) max = v; }); });
    var days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], h = '<table class="heat"><tr><th></th>';
    for (var i = 0; i < 24; i++) h += "<th>" + i + "</th>";
    h += "</tr>";
    grid.forEach(function (row, d) {
      h += "<tr><th>" + days[d] + "</th>";
      row.forEach(function (v, hr) {
        var a = max ? Math.min(1, v / max) : 0;
        h += '<td title="' + days[d] + " " + hr + ":00 - " + v + " " + (unit || "") + '" style="background:rgba(56,189,248,' + (v ? (0.12 + 0.88 * a).toFixed(2) : 0.04) + ')">' + (v || "") + "</td>";
      });
      h += "</tr>";
    });
    el.innerHTML = h + "</table>";
  };

  /* sub-tabs inside one page: <div class="subtabs"><button data-tab="x">..</div> + <section class="subpane" id="tab-x"> */
  BS.subtabs = function () {
    var btns = Array.prototype.slice.call(document.querySelectorAll(".subtabs [data-tab]"));
    if (!btns.length) return;
    var show = function (name, push) {
      btns.forEach(function (b) { b.classList.toggle("on", b.dataset.tab === name); });
      document.querySelectorAll(".subpane").forEach(function (p) { p.classList.toggle("on", p.id === "tab-" + name); });
      if (push) { try { history.replaceState(null, "", "#" + name); } catch (e) {} }
      window.dispatchEvent(new Event("resize"));      // lets Chart.js size charts that were hidden
    };
    btns.forEach(function (b) { b.addEventListener("click", function () { show(b.dataset.tab, true); }); });
    var h = (location.hash || "").slice(1);
    show(btns.some(function (b) { return b.dataset.tab === h; }) ? h : btns[0].dataset.tab, false);
  };

  BS.viewToggle = function () {
    var box = document.getElementById("usersBox");
    if (!box) return;
    document.querySelectorAll("[data-view]").forEach(function (b) {
      b.addEventListener("click", function () {
        box.className = "view-" + b.dataset.view;
        document.querySelectorAll("[data-view]").forEach(function (x) { x.classList.toggle("on", x === b); });
      });
    });
  };

  document.addEventListener("DOMContentLoaded", function () {
    var t = document.getElementById("themeBtn");
    var label = function () { if (t) t.textContent = root.getAttribute("data-theme") === "light" ? "🌙 Dark" : "☀️ Light"; };
    label();
    if (t) t.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      try { localStorage.setItem("bs_staff_theme", next); } catch (e) {}
      location.reload();
    });
    BS.subtabs(); BS.viewToggle();
    if (typeof window.BS_PAGE === "function") window.BS_PAGE();
  });
})();
