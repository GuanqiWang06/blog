(function () {
  "use strict";

  var root = document.documentElement;
  var toggle = document.querySelector("[data-theme-toggle]");
  var themeColorMeta = document.querySelector('meta[name="theme-color"]');

  function isDark() {
    return root.getAttribute("data-theme") === "dark";
  }

  function syncToggle() {
    if (themeColorMeta) {
      themeColorMeta.setAttribute("content", isDark() ? "#121212" : "#ffffff");
    }
    if (!toggle) return;
    toggle.setAttribute("aria-pressed", String(isDark()));
    toggle.setAttribute("aria-label", isDark() ? "切换到浅色模式" : "切换到深色模式");
    toggle.setAttribute("title", isDark() ? "切换到浅色模式" : "切换到深色模式");
  }

  if (toggle) {
    syncToggle();
    toggle.addEventListener("click", function () {
      var next = isDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("theme", next);
      } catch (error) {
        /* 隐私模式下无法写入，忽略即可 */
      }
      syncToggle();
    });
  }
})();
