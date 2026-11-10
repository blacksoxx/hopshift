// Applies the saved theme before the app renders so there is no flash. Served from /theme.js
// (an external file) so the strict Content-Security-Policy can keep inline scripts disabled.
(function () {
  try {
    var stored = localStorage.getItem("hopshift.theme");
    var dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {
    /* ignore */
  }
})();
