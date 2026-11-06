/* Runs before the page is painted so there is no dark/light "flash". Remembers the choice; follows the device setting at first. */
(function () {
  var t = null;
  try { t = localStorage.getItem("biospine_theme"); } catch (e) {}
  if (t !== "light" && t !== "dark") t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", t);
  var m = document.querySelector('meta[name="theme-color"]');
  if (m) m.setAttribute("content", t === "light" ? "#f1f5fb" : "#070d18");
})();
