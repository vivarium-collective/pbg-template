// walkthrough.js — adds a "Copy" button to the wizard panel.
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var panel = document.getElementById("walkthrough-panel");
    if (!panel) return;
    var pre = panel.querySelector("pre");
    if (!pre) return;
    var btn = document.createElement("button");
    btn.textContent = "Copy command";
    btn.style.cssText = "margin-top:8px;padding:4px 10px;border:1px solid #f5b042;background:#fff;cursor:pointer;border-radius:4px";
    btn.addEventListener("click", function () {
      var text = pre.querySelector("code").innerText;
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copied ✓";
        setTimeout(function () { btn.textContent = "Copy command"; }, 1500);
      });
    });
    pre.parentNode.insertBefore(btn, pre.nextSibling);
  });
})();
