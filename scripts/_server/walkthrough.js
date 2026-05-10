// walkthrough.js — v0.3.7-A: _installImport (pip-install button); v0.3.6: Registry tab, simulation processes picker; v0.1.9: drag-drop uploads + sha256; v0.1.7: interactive forms.
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

  function _showBranchDiff(branch, rowEl) {
    var detailId = "branch-diff-" + branch.replace(/[^a-zA-Z0-9]/g, "_");
    var existing = document.getElementById(detailId);
    if (existing) {
      existing.style.display = existing.style.display === "none" ? "" : "none";
      return;
    }
    fetch("/api/branch-diff?branch=" + encodeURIComponent(branch))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var details = document.createElement("tr");
        details.id = detailId;
        var content = "";
        if (data.error) {
          content = "<em style='color:#c00'>Error: " + _esc(data.error) + "</em>";
        } else {
          content = "<details open><summary><strong>diff</strong></summary><pre style='font-size:0.8em;background:#f8f8f8;padding:8px;border-radius:4px;overflow-x:auto'>" +
            _esc((data.log || "(no commits)") + (data.diff_stat ? "\n---\n" + data.diff_stat : "")) +
            "</pre></details>";
        }
        details.innerHTML = "<td colspan='6' style='padding:8px 12px'>" + content + "</td>";
        if (rowEl && rowEl.parentNode) {
          rowEl.parentNode.insertBefore(details, rowEl.nextSibling);
        }
      })
      .catch(function(err) {
        var details = document.createElement("tr");
        details.id = detailId;
        details.innerHTML = "<td colspan='6' style='color:#c00'>Network error: " + _esc(String(err)) + "</td>";
        if (rowEl && rowEl.parentNode) {
          rowEl.parentNode.insertBefore(details, rowEl.nextSibling);
        }
      });
  }

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
        var table = document.createElement("table");
        table.innerHTML = "<thead><tr><th>Branch</th><th>SHA</th><th>Subject</th><th>Date</th><th>Ahead</th><th>Actions</th></tr></thead><tbody></tbody>";
        var tbody = table.querySelector("tbody");
        branches.forEach(function(b) {
          var sha = (b.last_commit && b.last_commit.sha) ? b.last_commit.sha : "?";
          var subject = (b.last_commit && b.last_commit.subject) ? b.last_commit.subject : "";
          var date = (b.last_commit && b.last_commit.date) ? b.last_commit.date.slice(0, 10) : "";
          var ahead = b.ahead_of_main || 0;
          var tr = document.createElement("tr");
          tr.innerHTML =
            "<td><code>" + _esc(b.name) + "</code></td>" +
            "<td><code>" + _esc(sha) + "</code></td>" +
            "<td>" + _esc(subject) + "</td>" +
            "<td>" + _esc(date) + "</td>" +
            "<td><span style='background:#e8f5e9;color:#2e7d32;border-radius:3px;padding:1px 6px;font-size:0.82em'>+" + ahead + "</span></td>" +
            "<td></td>";
          var actCell = tr.querySelector("td:last-child");
          // Copy gh pr create button
          var btnPR = document.createElement("button");
          btnPR.className = "pill-btn";
          btnPR.textContent = "Copy gh pr create";
          btnPR.title = "Copy: gh pr create --base main --head " + b.name;
          btnPR.onclick = function() {
            navigator.clipboard.writeText("gh pr create --base main --head " + b.name).then(function() {
              btnPR.textContent = "Copied!";
              setTimeout(function() { btnPR.textContent = "Copy gh pr create"; }, 1500);
            });
          };
          actCell.appendChild(btnPR);
          // Copy git merge button
          var btnMerge = document.createElement("button");
          btnMerge.className = "pill-btn";
          btnMerge.textContent = "Copy git merge";
          btnMerge.title = "Copy: git merge " + b.name;
          btnMerge.onclick = function() {
            navigator.clipboard.writeText("git merge " + b.name).then(function() {
              btnMerge.textContent = "Copied!";
              setTimeout(function() { btnMerge.textContent = "Copy git merge"; }, 1500);
            });
          };
          actCell.appendChild(btnMerge);
          // Show diff button
          var btnDiff = document.createElement("button");
          btnDiff.className = "pill-btn";
          btnDiff.textContent = "Show diff";
          btnDiff.onclick = function() { _showBranchDiff(b.name, tr); };
          actCell.appendChild(btnDiff);
          tbody.appendChild(tr);
        });
        container.innerHTML = "";
        container.appendChild(table);
      })
      .catch(function () {
        if (container) container.innerHTML = "<p style='color:#c00'>Could not load branches (server not running?).</p>";
      });
  }

  function _postPhaseAction(endpoint, data) {
    fetch("/api/" + endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], json = parts[1];
        if (!ok) {
          alert("Error: " + (json.error || "unknown"));
          return;
        }
        var msg = "Done! Branch: " + (json.branch || "?");
        fetch("/api/render", {method: "POST"}).finally(function() {
          alert(msg);
          location.reload();
        });
      })
      .catch(function(err) { alert("Network error: " + err); });
  }
  window._postPhaseAction = _postPhaseAction;

  // -------------------------------------------------------------------------
  // Menu navigation (v0.3.5)
  // -------------------------------------------------------------------------

  function _switchPage(pageId) {
    pageId = pageId || 'workspace-inputs';
    document.querySelectorAll('.page').forEach(function(s) { s.classList.remove('active'); });
    document.querySelectorAll('.menu-link').forEach(function(a) { a.classList.remove('active'); });
    var page = document.getElementById('page-' + pageId);
    var link = document.querySelector('.menu-link[data-page="' + pageId + '"]');
    if (page) page.classList.add('active');
    if (link) link.classList.add('active');
    // Lazy-load registry on first switch to Registry page.
    if (pageId === 'registry' && !window._registryLoaded) {
      window._registryLoaded = true;
      _loadRegistry(false);
    }
  }

  function _initMenuNav() {
    function fromHash() {
      var h = (window.location.hash || '').replace(/^#/, '');
      // phase anchors (#phase-N) auto-route to build-model page
      if (/^phase-\d+$/.test(h)) {
        _switchPage('build-model');
        // let the browser scroll to the anchor naturally
        return;
      }
      var validPages = ['workspace-inputs', 'simulation-setup', 'visualizations', 'registry', 'build-model'];
      _switchPage(validPages.indexOf(h) >= 0 ? h : 'workspace-inputs');
    }
    window.addEventListener('hashchange', fromHash);
    fromHash();
  }

  window._switchPage = _switchPage;
  window._initMenuNav = _initMenuNav;

  // -------------------------------------------------------------------------
  // Registry tab (v0.3.6)
  // -------------------------------------------------------------------------

  function _renderRegistryTable(items, container, kind) {
    if (!items || items.length === 0) {
      container.innerHTML = '<p class="empty-state">No ' + kind + ' registered.</p>';
      return;
    }
    var rows = items.map(function(it) {
      var schemaPreview = it.schema_preview || '';
      var escaped = schemaPreview.replace(/[<>&]/g, function(c) {
        return {'<': '&lt;', '>': '&gt;', '&': '&amp;'}[c];
      });
      var schemaCol = '<code class="registry-schema">' + (escaped ? escaped : '<em class="muted">—</em>') + '</code>';
      var addrCol = it.address ? '<code>' + it.address + '</code>' : '';
      if (kind === 'processes') {
        return '<tr><td><code>' + it.name + '</code></td><td>' + addrCol + '</td><td>' + schemaCol + '</td></tr>';
      } else {
        return '<tr><td><code>' + it.name + '</code></td><td>' + schemaCol + '</td></tr>';
      }
    }).join('');
    var headers = kind === 'processes'
      ? '<thead><tr><th>Name</th><th>Address</th><th>Config schema (preview)</th></tr></thead>'
      : '<thead><tr><th>Name</th><th>Definition (preview)</th></tr></thead>';
    container.innerHTML = '<table>' + headers + '<tbody>' + rows + '</tbody></table>';
  }

  function _loadRegistry(refresh) {
    var status = document.getElementById('registry-status');
    if (status) status.textContent = 'Loading…';
    fetch('/api/registry' + (refresh ? '?refresh=1' : ''))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (status) {
          if (data.error) {
            status.innerHTML = '<span style="color:#991b1b">⚠ ' + data.error + '</span>';
          } else {
            status.textContent = '';
          }
        }
        var procContainer = document.getElementById('registry-processes-container');
        var typeContainer = document.getElementById('registry-types-container');
        if (procContainer) _renderRegistryTable(data.processes || [], procContainer, 'processes');
        if (typeContainer) _renderRegistryTable(data.types || [], typeContainer, 'types');
        var procCount = document.getElementById('registry-process-count');
        var typeCount = document.getElementById('registry-type-count');
        if (procCount) procCount.textContent = '(' + (data.processes || []).length + ')';
        if (typeCount) typeCount.textContent = '(' + (data.types || []).length + ')';

        // Populate sim-process picker if present.
        var picker = document.getElementById('sim-process-picker');
        if (picker) {
          var procs = data.processes || [];
          if (procs.length === 0) {
            picker.innerHTML = '<p class="muted">No processes registered yet.</p>';
          } else {
            picker.innerHTML = procs.map(function(p) {
              return '<label style="display:inline-block; margin-right:12px">' +
                '<input type="checkbox" name="processes" value="' + p.name + '"> ' + p.name +
                '</label>';
            }).join('');
          }
        }
      })
      .catch(function(err) {
        if (status) status.innerHTML = '<span style="color:#991b1b">Network error: ' + err + '</span>';
      });
  }

  window._loadRegistry = _loadRegistry;

  // -------------------------------------------------------------------------
  // Simulation CRUD (v0.3.5)
  // -------------------------------------------------------------------------

  function _parseJSONorNull(s) {
    s = (s || '').trim();
    if (!s) return null;
    try { return JSON.parse(s); }
    catch (e) { throw new Error("Invalid JSON: " + e.message); }
  }

  function _submitSimulation(form) {
    try {
      var data = {
        name: form.sim_name.value.trim(),
        description: form.description.value.trim() || null,
        t_start: parseFloat(form.t_start.value),
        t_end: parseFloat(form.t_end.value),
        initial_state: _parseJSONorNull(form.initial_state.value),
        parameter_overrides: _parseJSONorNull(form.parameter_overrides.value),
        emitter_config: _parseJSONorNull(form.emitter_config.value),
        phases: Array.from(form.querySelectorAll('input[name=phases]:checked'))
                      .map(function(el) { return parseInt(el.value, 10); }),
        processes: Array.from(form.querySelectorAll('input[name=processes]:checked'))
                        .map(function(el) { return el.value; }),
      };
      submitForm(form, '/api/simulation', function() { return data; });
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  function _deleteSimulation(name) {
    if (!confirm("Remove simulation '" + name + "'?")) return;
    fetch('/api/simulation', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        if (!parts[0]) { alert("Error: " + (parts[1].error || "unknown")); return; }
        fetch('/api/render', {method: 'POST'}).finally(function() { location.reload(); });
      });
  }

  window._submitSimulation = _submitSimulation;
  window._deleteSimulation = _deleteSimulation;
  window._parseJSONorNull = _parseJSONorNull;

  // -------------------------------------------------------------------------
  // Import install (v0.3.7-A)
  // -------------------------------------------------------------------------

  function _installImport(name) {
    if (!confirm("Pip install '" + name + "' into workspace venv?\nThis runs `.venv/bin/pip install -e <path>` and may take a minute.")) return;
    var btn = event.target;
    btn.disabled = true;
    btn.textContent = "Installing…";
    fetch('/api/import-install', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], json = parts[1];
        if (!ok) {
          alert("Install failed:\n\n" + (json.error || 'unknown') + "\n\n" + (json.log || ''));
          btn.disabled = false;
          btn.textContent = "Install";
          return;
        }
        alert("Installed.\nBranch: " + json.branch + "\n\nRegistry will refresh; new processes may appear after pip-cached subprocess restarts.");
        // Drop registry cache, switch to Registry tab so user sees the change.
        window._registryLoaded = false;
        fetch('/api/render', {method: 'POST'}).finally(function() {
          location.hash = '#registry';
          location.reload();
        });
      })
      .catch(function(err) { alert("Network error: " + err); btn.disabled = false; });
  }
  window._installImport = _installImport;

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
  // Drop-zone helper (v0.1.9)
  // -------------------------------------------------------------------------

  /**
   * setupDropZone(zoneId, storeKey)
   *
   * Attaches drag-drop behaviour to the element with id=zoneId.
   * On drop:
   *   1. Reads the first file as a DataURL.
   *   2. Strips the data:*;base64, prefix to get pure base64.
   *   3. Computes a browser-side sha256 (transparency only; server recomputes).
   *   4. Updates the drop zone with filename + size + hash.
   *   5. Stores {file_b64, filename} in _dropZoneStore[storeKey].
   */
  var _dropZoneStore = {};

  function setupDropZone(zoneId, storeKey) {
    var zone = document.getElementById(zoneId);
    if (!zone) return;

    function prevent(e) { e.preventDefault(); e.stopPropagation(); }

    zone.addEventListener("dragenter", function(e) { prevent(e); zone.classList.add("drag-over"); });
    zone.addEventListener("dragover",  function(e) { prevent(e); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", function(e) { prevent(e); zone.classList.remove("drag-over"); });
    zone.addEventListener("drop", function(e) {
      prevent(e);
      zone.classList.remove("drag-over");
      var file = e.dataTransfer.files[0];
      if (!file) return;
      _readFile(file, zone, storeKey);
    });

    // Also allow click-to-select (creates a hidden file input).
    zone.addEventListener("click", function() {
      var inp = document.createElement("input");
      inp.type = "file";
      inp.style.display = "none";
      inp.onchange = function() {
        if (inp.files && inp.files[0]) {
          _readFile(inp.files[0], zone, storeKey);
        }
      };
      document.body.appendChild(inp);
      inp.click();
      setTimeout(function() { document.body.removeChild(inp); }, 30000);
    });
  }

  function _readFile(file, zone, storeKey) {
    var reader = new FileReader();
    reader.onload = function(ev) {
      var dataUrl = ev.target.result;
      // Strip "data:<mime>;base64," prefix.
      var comma = dataUrl.indexOf(",");
      var b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;

      // Browser-side sha256 for transparency.
      var rawBytes = _b64ToUint8Array(b64);
      crypto.subtle.digest("SHA-256", rawBytes).then(function(hashBuf) {
        var hashArr = Array.from(new Uint8Array(hashBuf));
        var hashHex = hashArr.map(function(b) { return b.toString(16).padStart(2, "0"); }).join("");

        _dropZoneStore[storeKey] = { file_b64: b64, filename: file.name };

        var sizeKb = (file.size / 1024).toFixed(1);
        var infoEl = zone.querySelector(".file-info");
        var hashEl = zone.querySelector(".file-hash");
        if (infoEl) infoEl.textContent = file.name + " (" + sizeKb + " KB)";
        if (hashEl) hashEl.textContent = "sha256: " + hashHex;
        zone.style.borderColor = "#3a8";
        zone.querySelector && (zone.querySelectorAll(".drop-hint").forEach(function(h) { h.style.display = "none"; }));
      });
    };
    reader.readAsDataURL(file);
  }

  function _b64ToUint8Array(b64) {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  // -------------------------------------------------------------------------
  // Expose globals
  // -------------------------------------------------------------------------

  window.openModal = openModal;
  window.closeModal = closeModal;
  window.submitForm = submitForm;
  window.loadBranches = loadBranches;
  window.runTests = runTests;
  window.setupDropZone = setupDropZone;
  window._dropZoneStore = _dropZoneStore;
  window._showBranchDiff = _showBranchDiff;

  // -------------------------------------------------------------------------
  // Copy-command button (legacy walkthrough-panel support)
  // -------------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    // Initialize menu navigation.
    _initMenuNav();

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
