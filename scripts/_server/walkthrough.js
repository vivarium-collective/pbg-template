// walkthrough.js — v0.1.7: interactive forms, auto-branch/commit, branch timeline.
(function () {
  "use strict";

  // -------------------------------------------------------------------------
  // Generic modal helpers
  // -------------------------------------------------------------------------

  function openModal(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = "flex";
  }

  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) {
      el.style.display = "none";
      // Clear inline errors.
      var errEl = el.querySelector(".form-error");
      if (errEl) errEl.textContent = "";
    }
  }

  // Close modals when clicking the overlay background.
  document.addEventListener("click", function (e) {
    if (e.target && e.target.classList.contains("modal-overlay")) {
      e.target.style.display = "none";
    }
  });

  // -------------------------------------------------------------------------
  // Form submission helper
  // -------------------------------------------------------------------------

  /**
   * submitForm — POST form data as JSON to endpoint.
   * On success: alert message, call /api/render, then reload.
   * On error: show inline error inside the form.
   *
   * @param {HTMLFormElement} form
   * @param {string} endpoint
   * @param {function} [dataFn] — optional fn(form) -> object; defaults to FormData extraction
   */
  function submitForm(form, endpoint, dataFn) {
    var errEl = form.querySelector(".form-error");
    if (errEl) errEl.textContent = "";

    var submitBtn = form.querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = true;

    var data = dataFn ? dataFn(form) : _formToObj(form);

    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (res) {
        return res.json().then(function (json) {
          return { ok: res.ok, status: res.status, json: json };
        });
      })
      .then(function (r) {
        if (!r.ok) {
          var msg = (r.json && r.json.error) ? r.json.error : ("HTTP " + r.status);
          if (errEl) errEl.textContent = "Error: " + msg;
          if (submitBtn) submitBtn.disabled = false;
          return;
        }
        var branch = r.json.branch || "";
        var commit = r.json.commit || "";
        var note = r.json.note || "";
        var next = r.json.next_terminal_step || "";
        var msg = "Done!";
        if (branch) msg += " Branch: " + branch + (commit ? " (" + commit + ")" : "");
        if (next) msg += "\n\nNext terminal step:\n  " + next;
        if (note) msg += "\n\n" + note;
        // Re-render then reload.
        fetch("/api/render", { method: "POST" }).finally(function () {
          alert(msg);
          location.reload();
        });
      })
      .catch(function (err) {
        if (errEl) errEl.textContent = "Network error: " + String(err);
        if (submitBtn) submitBtn.disabled = false;
      });
  }

  function _formToObj(form) {
    var obj = {};
    var data = new FormData(form);
    data.forEach(function (val, key) {
      if (obj[key] !== undefined) {
        // Multi-value: accumulate into array.
        if (!Array.isArray(obj[key])) obj[key] = [obj[key]];
        obj[key].push(val);
      } else {
        obj[key] = val;
      }
    });
    return obj;
  }

  // -------------------------------------------------------------------------
  // Branch timeline
  // -------------------------------------------------------------------------

  function loadBranches() {
    var container = document.getElementById("branch-timeline-body");
    if (!container) return;
    fetch("/api/branches")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var branches = data.branches || [];
        if (!branches.length) {
          container.innerHTML = "<p style='color:#888;font-style:italic'>No stage/* branches yet. Each browser action creates one.</p>";
          return;
        }
        var rows = branches.map(function (b) {
          var sha = (b.last_commit && b.last_commit.sha) ? b.last_commit.sha : "?";
          var subject = (b.last_commit && b.last_commit.subject) ? b.last_commit.subject : "";
          var date = (b.last_commit && b.last_commit.date) ? b.last_commit.date.slice(0, 10) : "";
          var ahead = b.ahead_of_main || 0;
          return "<tr>" +
            "<td><code>" + _esc(b.name) + "</code></td>" +
            "<td><code>" + _esc(sha) + "</code></td>" +
            "<td>" + _esc(subject) + "</td>" +
            "<td>" + _esc(date) + "</td>" +
            "<td><span style='background:#e8f5e9;color:#2e7d32;border-radius:3px;padding:1px 6px;font-size:0.82em'>+" + ahead + "</span></td>" +
            "</tr>";
        }).join("");
        container.innerHTML = "<table><thead><tr><th>Branch</th><th>SHA</th><th>Subject</th><th>Date</th><th>Ahead</th></tr></thead><tbody>" + rows + "</tbody></table>";
      })
      .catch(function () {
        if (container) container.innerHTML = "<p style='color:#c00'>Could not load branches (server not running?).</p>";
      });
  }

  // -------------------------------------------------------------------------
  // Run tests
  // -------------------------------------------------------------------------

  function runTests(model) {
    var btn = document.getElementById("run-tests-btn");
    var out = document.getElementById("run-tests-output");
    var spinner = document.getElementById("run-tests-spinner");
    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline";
    if (out) out.textContent = "Running…";

    fetch("/api/run-tests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: model }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (data.error) {
          if (out) out.textContent = "Error: " + data.error;
          return;
        }
        var text = (data.stdout || "") + (data.stderr ? "\n--- stderr ---\n" + data.stderr : "");
        var rc = data.returncode;
        if (out) {
          out.textContent = text || "(no output)";
          out.style.background = rc === 0 ? "#f0fff0" : "#fff0f0";
          out.style.borderColor = rc === 0 ? "#4caf50" : "#f44336";
        }
      })
      .catch(function (err) {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (out) out.textContent = "Network error: " + String(err);
      });
  }

  // -------------------------------------------------------------------------
  // Expose globals
  // -------------------------------------------------------------------------

  window.openModal = openModal;
  window.closeModal = closeModal;
  window.submitForm = submitForm;
  window.loadBranches = loadBranches;
  window.runTests = runTests;

  // -------------------------------------------------------------------------
  // Copy-command button (legacy walkthrough-panel support)
  // -------------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    var panel = document.getElementById("walkthrough-panel");
    if (panel) {
      var pre = panel.querySelector("pre");
      if (pre) {
        var btn = document.createElement("button");
        btn.textContent = "Copy command";
        btn.style.cssText = "margin-top:8px;padding:4px 10px;border:1px solid #f5b042;background:#fff;cursor:pointer;border-radius:4px";
        btn.addEventListener("click", function () {
          var code = pre.querySelector("code");
          var text = code ? code.innerText : pre.innerText;
          navigator.clipboard.writeText(text).then(function () {
            btn.textContent = "Copied";
            setTimeout(function () { btn.textContent = "Copy command"; }, 1500);
          });
        });
        pre.parentNode.insertBefore(btn, pre.nextSibling);
      }
    }

    // Auto-load branches if the branch timeline container exists.
    if (document.getElementById("branch-timeline-body")) {
      loadBranches();
    }
  });

  // -------------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------------

  function _esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

})();
