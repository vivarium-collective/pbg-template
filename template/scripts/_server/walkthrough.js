// walkthrough.js — v0.5.3: investigation detail panel — Spec/Runs/Visualizations tabs + Run button + Delete; v0.5.2: composite explorer UX fixes (no focus-mode hijack, one-row-per-param layout, lazy-load composite cache); v0.5.1: composite explorer page (bigraph-viz + test run + promote to simulation); v0.4.14: Available Composites picker + Emitter Use feedback + drop process multi-select; v0.4.5: _renderInstallError structured diagnosis; v0.4.1: _loadCatalog + _installFromCatalog; v0.4.0b: active-branch workstream strip; v0.3.7-A: _installImport; v0.3.6: Registry tab; v0.1.9: drag-drop uploads; v0.1.7: interactive forms.
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

  // Global listener for postMessage events from loom-explore iframes.
  window.addEventListener('message', function(ev) {
    if (ev.data && ev.data.type === 'explore:ready') {
      // Mark the source iframe as ready so callers can post immediately.
      var ids = ['composite-explore-frame', 'inv-composite-explore-frame'];
      ids.forEach(function(id) {
        var iframe = document.getElementById(id);
        if (iframe && ev.source === iframe.contentWindow) {
          window._loomExploreReady = window._loomExploreReady || {};
          window._loomExploreReady[id] = true;
        }
      });
    }
    if (ev.data && ev.data.type === 'explore:inspect') {
      console.log('[loom-explore inspect]', ev.data);
      // TODO: cross-panel highlighting (out of scope for this task)
    }
  });

  // -------------------------------------------------------------------------
  // UI feature flags (ui.composite_view)
  // -------------------------------------------------------------------------
  window._uiConfig = null;
  fetch('/api/ui-config').then(function(r) { return r.json(); }).then(function(cfg) {
    window._uiConfig = cfg || {};
    _applyCompositeViewMode();
  });

  function _applyCompositeViewMode() {
    var cfg = window._uiConfig || {};
    var mode = cfg.composite_view || 'loom-explore';
    var iframe = document.getElementById('composite-explore-frame');
    var svgLegacy = document.getElementById('composite-explore-svg-legacy');
    if (!iframe || !svgLegacy) return;
    if (mode === 'bigraph-viz') {
      iframe.style.display = 'none';
      svgLegacy.style.display = '';
    } else {
      iframe.style.display = '';
      svgLegacy.style.display = 'none';
    }
  }
  window._applyCompositeViewMode = _applyCompositeViewMode;

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
        // Re-render then reload (strip updates on reload).
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
          _refreshWorkStrip();
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
    // Lazy-load catalog + registry on switch to Registry, Simulation Setup, or Visualizations page.
    if (pageId === 'registry') {
      _loadCatalog();
    }
    if (pageId === 'registry' || pageId === 'simulation-setup' || pageId === 'visualizations') {
      if (!window._registryLoaded) {
        window._registryLoaded = true;
        _loadRegistry(false);
      }
    }
    if (pageId === 'simulation-setup') {
      _loadComposites();
    }
    // Lazy-load branches when switching to the Branches tab.
    if (pageId === 'branches') {
      if (!window._branchesLoaded) {
        window._branchesLoaded = true;
        loadBranches();
      }
    }
    // Initialize composite explorer when switching to that page.
    if (pageId === 'composite-explore') {
      _initCompositeExplorer();
    }
    if (pageId === 'investigations') {
      if (!window._investigationsLoaded) {
        window._investigationsLoaded = true;
        _loadInvestigations();
      }
    }
  }

  function _initMenuNav() {
    // Focus mode: ?focus=<panel> hides everything except the named panel.
    var params = new URLSearchParams(window.location.search);
    var focus = params.get('focus');
    if (focus) {
      var validPages = ['workspace-inputs', 'simulation-setup', 'visualizations', 'registry', 'investigations', 'branches', 'composite-explore'];
      if (validPages.indexOf(focus) >= 0) {
        document.body.classList.add('focus-mode', 'focus-' + focus);
        _switchPage(focus);
        return; // skip normal hash-based routing
      }
    }

    function fromHash() {
      var h = (window.location.hash || '').replace(/^#/, '');
      var validPages = ['workspace-inputs', 'registry', 'simulation-setup', 'visualizations', 'investigations', 'branches', 'composite-explore'];
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

  function _esc(s) {
    return String(s || '').replace(/[<>&"]/g, function(c) {
      return {'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c];
    });
  }

  function _filterVizCatalog(query) {
    var rows = document.querySelectorAll('#viz-picker-container .picker-row');
    var q = (query || '').toLowerCase().trim();
    rows.forEach(function(row) {
      if (!q) { row.style.display = ''; return; }
      var hay = (row.textContent || '').toLowerCase();
      row.style.display = hay.indexOf(q) === -1 ? 'none' : '';
    });
  }
  window._filterVizCatalog = _filterVizCatalog;

  function _renderKindPicker(items, container, kind) {
    if (!items || items.length === 0) {
      container.innerHTML = '<p class="empty-state">No ' + kind + 's registered. Install a pbg-* package that provides one (Registry tab &rarr; Available modules).</p>';
      return;
    }
    var rows = items.map(function(it) {
      var schemaSnippet = '';
      if (it.schema_preview) {
        schemaSnippet = '<details><summary class="muted" style="cursor:pointer;font-size:0.85em">config_schema</summary><code class="registry-schema">' + _esc(it.schema_preview) + '</code></details>';
      }
      var previewBtn = (kind === 'visualization')
        ? '<button class="btn-mini" onclick="_vizClassPreview(\'' + _esc(it.address) + '\',\'' + _esc(it.name) + '\')">Preview</button>'
        : '';
      return '<div class="picker-row">' +
        '<div class="picker-row-main">' +
          '<strong>' + _esc(it.name) + '</strong>' +
          ' <code class="muted" style="font-size:0.82em">' + _esc(it.address) + '</code>' +
          schemaSnippet +
        '</div>' +
        '<div class="picker-row-actions">' +
          previewBtn +
          '<button class="btn-mini" onclick="_useRegistryClass(\'' + kind + '\', \'' + _esc(it.name) + '\')">Use</button>' +
        '</div>' +
      '</div>';
    }).join('');
    container.innerHTML = rows;
  }

  function _useRegistryClass(kind, name) {
    if (kind === 'emitter') {
      _switchPage('simulation-setup');
      // Find the inline simulation form (inside a <details> in Simulation Setup)
      var form = document.getElementById('form-simulation');
      if (!form) return;
      var details = form.closest('details');
      if (details) details.open = true;
      var ta = form.querySelector('textarea[name=emitter_config]');
      if (ta) {
        ta.value = JSON.stringify({address: 'local:' + name, config: {}}, null, 2);
        // Highlight the textarea so user notices
        ta.classList.add('highlight-flash');
        setTimeout(function() { ta.classList.remove('highlight-flash'); }, 1500);
        // Scroll into view
        ta.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
      // Show a transient banner
      var banner = document.createElement('div');
      banner.className = 'apply-banner';
      banner.textContent = name + ' applied to next Add simulation — review and submit below';
      form.parentNode.insertBefore(banner, form);
      setTimeout(function() { banner.remove(); }, 4000);
    } else if (kind === 'visualization') {
      // Open the workspace Add-Visualization modal pre-configured as a
      // class-backed instance of this Visualization class.
      _openWorkspaceVizModal();
      // Defer until the modal's promise has populated the class dropdown.
      var attempts = 0;
      var tryFill = function() {
        var sel = document.getElementById('viz-class-picker');
        if (!sel || sel.options.length <= 1) {
          if (attempts++ < 20) return setTimeout(tryFill, 60);
          return;
        }
        var modal = document.getElementById('modal-visualization');
        var nameInput = modal && modal.querySelector('input[name=viz_name]');
        if (nameInput && !nameInput.value) {
          nameInput.value = name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
        }
        // Select the matching class option
        for (var i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value === name) { sel.selectedIndex = i; break; }
        }
      };
      setTimeout(tryFill, 60);
    }
  }
  window._useRegistryClass = _useRegistryClass;

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

        // Populate emitter picker (Simulation Setup tab).
        var emitters = (data.processes || []).filter(function(p) { return p.kind === 'emitter'; });
        var emitterContainer = document.getElementById('emitter-picker-container');
        if (emitterContainer) _renderKindPicker(emitters, emitterContainer, 'emitter');
        var emitterCount = document.getElementById('emitter-count');
        if (emitterCount) emitterCount.textContent = '(' + emitters.length + ')';

        // Populate visualization picker (Visualizations tab).
        var visualizations = (data.processes || []).filter(function(p) { return p.kind === 'visualization'; });
        var vizContainer = document.getElementById('viz-picker-container');
        if (vizContainer) _renderKindPicker(visualizations, vizContainer, 'visualization');
        var vizCount = document.getElementById('viz-count');
        if (vizCount) vizCount.textContent = '(' + visualizations.length + ')';
      })
      .catch(function(err) {
        if (status) status.innerHTML = '<span style="color:#991b1b">Network error: ' + err + '</span>';
      });
  }

  window._loadRegistry = _loadRegistry;

  // -------------------------------------------------------------------------
  // Composites browser (v0.5.6: search + tag chips + list view)
  // -------------------------------------------------------------------------

  window._composites = [];
  window._compositesFilter = { search: '', tags: new Set() };
  window._compositesView = 'grid';

  function _buildCompositeChips() {
    var chipsEl = document.getElementById('composite-tag-chips');
    if (!chipsEl) return;
    var allTags = [];
    window._composites.forEach(function(c) {
      (c.tags || []).forEach(function(t) {
        if (allTags.indexOf(t) === -1) allTags.push(t);
      });
    });
    allTags.sort();
    chipsEl.innerHTML = allTags.map(function(t) {
      return '<button class="card-browse-chip" onclick="_toggleCompositeChip(this,\'' + _esc(t) + '\')">' + _esc(t) + '</button>';
    }).join('');
  }

  function _toggleCompositeChip(btn, tag) {
    if (window._compositesFilter.tags.has(tag)) {
      window._compositesFilter.tags.delete(tag);
      btn.classList.remove('active');
    } else {
      window._compositesFilter.tags.add(tag);
      btn.classList.add('active');
    }
    _renderComposites();
  }
  window._toggleCompositeChip = _toggleCompositeChip;

  function _setCompositeView(view) {
    window._compositesView = view;
    var btns = document.querySelectorAll('#composite-toolbar .view-btn');
    btns.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-view') === view);
    });
    _renderComposites();
  }
  window._setCompositeView = _setCompositeView;

  function _renderComposites() {
    var container = document.getElementById('composite-cards');
    if (!container) return;
    var f = window._compositesFilter;
    var search = f.search.toLowerCase();
    var activeTags = f.tags;
    var composites = window._composites.filter(function(c) {
      if (search) {
        var haystack = (c.name + ' ' + (c.description || '') + ' ' + (c.tags || []).join(' ')).toLowerCase();
        if (haystack.indexOf(search) === -1) return false;
      }
      if (activeTags.size > 0) {
        var cTags = c.tags || [];
        var match = false;
        activeTags.forEach(function(t) { if (cTags.indexOf(t) !== -1) match = true; });
        if (!match) return false;
      }
      return true;
    });

    if (!composites.length) {
      container.innerHTML = '<p class="empty-state">No composites match the current filter.</p>';
      container.className = '';
      return;
    }

    if (window._compositesView === 'list') {
      container.className = 'composite-list';
      var rows = composites.map(function(c) {
        var tagPills = (c.tags || []).map(function(t) {
          return '<span class="tag-pill">' + _esc(t) + '</span>';
        }).join('');
        return '<div class="composite-list-row">' +
          '<span class="name">' + _esc(c.name) + '</span>' +
          '<span class="desc">' + tagPills + ' ' + _esc(c.description || '(no description)') + '</span>' +
          '<span><button class="action-btn" onclick="_openCompositeExplorer(\'' + _esc(c.id) + '\')">Explore</button></span>' +
          '</div>';
      });
      container.innerHTML = rows.join('');
    } else {
      container.className = 'module-grid';
      var cards = composites.map(function(c) {
        var paramSummary = '';
        var paramKeys = Object.keys(c.parameters || {});
        if (paramKeys.length) {
          paramSummary = '<div class="module-tags">' +
            paramKeys.map(function(k) {
              return '<span class="tag-pill">' + _esc(k) + '</span>';
            }).join('') + '</div>';
        }
        var requires = '';
        if (c.requires && c.requires.processes && c.requires.processes.length) {
          requires = '<small class="muted">Requires: ' +
            c.requires.processes.map(_esc).join(', ') + '</small><br>';
        }
        var tagSummary = '';
        if (c.tags && c.tags.length) {
          tagSummary = '<div class="module-tags">' +
            c.tags.map(function(t) {
              return '<span class="tag-pill" style="background:#e0e7ff;color:#3730a3">' + _esc(t) + '</span>';
            }).join(' ') + '</div>';
        }
        return '<div class="module-card">' +
          '<div class="module-card-header"><strong>' + _esc(c.name) + '</strong></div>' +
          '<p class="module-desc">' + _esc(c.description || '(no description)') + '</p>' +
          requires +
          tagSummary +
          paramSummary +
          '<div class="module-action">' +
            '<button class="action-btn" onclick="_openCompositeExplorer(\'' + _esc(c.id) + '\')">Explore</button>' +
          '</div>' +
        '</div>';
      });
      container.innerHTML = cards.join('');
    }
  }
  window._renderComposites = _renderComposites;

  function _loadComposites() {
    fetch('/api/composites')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var container = document.getElementById('composite-cards');
        var countBadge = document.getElementById('composite-count');
        if (!container) return;
        var composites = data.composites || [];
        // Cache by id so onclick handlers pass just the id; _useComposite
        // looks the full object up. Inline JSON.stringify in onclick attrs
        // breaks when descriptions contain apostrophes / quotes.
        window._compositesById = {};
        composites.forEach(function(c) { window._compositesById[c.id] = c; });
        if (countBadge) countBadge.textContent = '(' + composites.length + ')';
        if (!composites.length) {
          container.innerHTML =
            '<p class="empty-state">No composite specs found yet. Add a <code>*.composite.yaml</code> file under ' +
            '<code>pbg_&lt;slug&gt;/composites/</code> to register one. See ' +
            '<a href="https://github.com/vivarium-collective/pbg-superpowers/blob/main/docs/conventions/composites.md" target="_blank">' +
            'the composite spec convention</a> for the format.</p>';
          return;
        }
        window._composites = composites;
        // Wire up search input
        var searchEl = document.getElementById('composite-search');
        if (searchEl && !searchEl._pbgWired) {
          searchEl._pbgWired = true;
          searchEl.oninput = function() {
            window._compositesFilter.search = this.value.toLowerCase();
            _renderComposites();
          };
        }
        _buildCompositeChips();
        _renderComposites();
      });
  }
  window._loadComposites = _loadComposites;

  function _useComposite(compositeOrId) {
    // Accept either a full composite object (legacy) or an id string.
    var composite = (typeof compositeOrId === 'string')
      ? (window._compositesById || {})[compositeOrId]
      : compositeOrId;
    if (!composite) {
      alert("Composite not found in cache. Reload the page and try again.");
      return;
    }
    var modal = document.getElementById('modal-configure-composite');
    if (!modal) return;
    var nameSpan = document.getElementById('cc-composite-name');
    if (nameSpan) {
      nameSpan.innerHTML = 'Composite: <code>' + _esc(composite.id) + '</code>';
    }
    var hiddenId = modal.querySelector('input[name=composite_id]');
    if (hiddenId) hiddenId.value = composite.id;
    // Pre-fill sim_name with a sensible default
    var simNameInput = modal.querySelector('input[name=sim_name]');
    if (simNameInput) simNameInput.value = composite.name + '-run';
    // Render parameter fields
    var fieldsContainer = document.getElementById('cc-parameter-fields');
    if (fieldsContainer) {
      var params = composite.parameters || {};
      var keys = Object.keys(params);
      if (!keys.length) {
        fieldsContainer.innerHTML = '<p class="muted" style="font-size:0.9em">No parameters to configure.</p>';
      } else {
        fieldsContainer.innerHTML = '<h4 style="margin:14px 0 6px;font-size:0.95em">Parameters</h4>' +
          keys.map(function(pname) {
            var pdef = params[pname];
            var inputType = (pdef.type === 'int' || pdef.type === 'float') ? 'number' : 'text';
            var step = (pdef.type === 'float') ? 'any' : (pdef.type === 'int' ? '1' : '');
            var def = pdef.default === undefined ? '' : String(pdef.default);
            var desc = pdef.description ? ('<small class="muted">' + _esc(pdef.description) + '</small>') : '';
            return '<label>' + _esc(pname) + ' <span class="muted">(' + (pdef.type || 'string') + ')</span>' +
              '<input name="param_' + _esc(pname) + '" type="' + inputType + '"' +
              (step ? ' step="' + step + '"' : '') +
              ' value="' + _esc(def) + '">' +
              desc +
            '</label>';
          }).join('');
      }
    }
    openModal('modal-configure-composite');
  }
  window._useComposite = _useComposite;

  function _submitConfigureComposite(form) {
    var data = {
      name: form.sim_name.value.trim(),
      composite: form.composite_id.value,
      t_start: parseFloat(form.t_start.value),
      t_end: parseFloat(form.t_end.value),
      parameter_overrides: {},
    };
    // Collect param_<name> fields
    Array.from(form.elements).forEach(function(el) {
      if (el.name && el.name.indexOf('param_') === 0 && el.value !== '') {
        var pname = el.name.substring('param_'.length);
        var v = el.value;
        // Cast based on input type
        if (el.type === 'number') v = parseFloat(v);
        data.parameter_overrides[pname] = v;
      }
    });
    submitForm(form, '/api/simulation', function() { return data; });
  }
  window._submitConfigureComposite = _submitConfigureComposite;

  // -------------------------------------------------------------------------
  // Catalog browser (v0.5.6: search + tag chips + list view + installed filter)
  // -------------------------------------------------------------------------

  window._catalogModules = [];
  window._catalogFilter = { search: '', tags: new Set(), installed: 'all' };
  window._catalogView = 'grid';

  function _buildCatalogChips() {
    var chipsEl = document.getElementById('catalog-tag-chips');
    if (!chipsEl) return;
    var allTags = [];
    window._catalogModules.forEach(function(m) {
      (m.tags || []).forEach(function(t) {
        if (allTags.indexOf(t) === -1) allTags.push(t);
      });
    });
    allTags.sort();
    chipsEl.innerHTML = allTags.map(function(t) {
      return '<button class="card-browse-chip" onclick="_toggleCatalogChip(this,\'' + _esc(t) + '\')">' + _esc(t) + '</button>';
    }).join('');
  }

  function _toggleCatalogChip(btn, tag) {
    if (window._catalogFilter.tags.has(tag)) {
      window._catalogFilter.tags.delete(tag);
      btn.classList.remove('active');
    } else {
      window._catalogFilter.tags.add(tag);
      btn.classList.add('active');
    }
    _renderCatalog();
  }
  window._toggleCatalogChip = _toggleCatalogChip;

  function _setCatalogView(view) {
    window._catalogView = view;
    var btns = document.querySelectorAll('#catalog-toolbar .view-btn');
    btns.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-view') === view);
    });
    _renderCatalog();
  }
  window._setCatalogView = _setCatalogView;

  function _renderCatalog() {
    var grid = document.getElementById('catalog-modules-grid');
    if (!grid) return;
    var f = window._catalogFilter;
    var search = f.search.toLowerCase();
    var activeTags = f.tags;
    var modules = window._catalogModules.filter(function(m) {
      // Search filter
      if (search) {
        var haystack = (m.name + ' ' + (m.description || '') + ' ' + (m.tags || []).join(' ')).toLowerCase();
        if (haystack.indexOf(search) === -1) return false;
      }
      // Installed filter
      if (f.installed === 'installed' && !m.installed) return false;
      if (f.installed === 'uninstalled' && m.installed) return false;
      // Tag chip filter (OR within: pass if any selected tag matches)
      if (activeTags.size > 0) {
        var mTags = m.tags || [];
        var match = false;
        activeTags.forEach(function(t) { if (mTags.indexOf(t) !== -1) match = true; });
        if (!match) return false;
      }
      return true;
    });

    if (!modules.length) {
      grid.innerHTML = '<p class="empty-state">No modules match the current filter.</p>';
      grid.className = '';
      return;
    }

    if (window._catalogView === 'list') {
      grid.className = 'module-list';
      var rows = modules.map(function(m) {
        var actionBtn = m.installed
          ? '<span class="status-pill installed">installed</span>' +
            ' <button class="action-btn action-btn--secondary" onclick="_uninstallFromCatalog(\'' + _esc(m.name) + '\')">Uninstall</button>'
          : '<button class="action-btn" onclick="_installFromCatalog(\'' + _esc(m.name) + '\')">Install</button>';
        var tagPills = (m.tags || []).map(function(t) {
          return '<span class="tag-pill">' + _esc(t) + '</span>';
        }).join('');
        return '<div class="module-list-row">' +
          '<span class="name">' + _esc(m.name) + '</span>' +
          '<span class="desc">' + tagPills + ' ' + _esc(m.description || '') + '</span>' +
          '<span>' + actionBtn + '</span>' +
          '</div>';
      });
      grid.innerHTML = rows.join('');
    } else {
      grid.className = 'module-grid';
      var cards = modules.map(function(m) {
        var actionBtn = m.installed
          ? '<span class="status-pill installed">installed</span>' +
            ' <button class="action-btn action-btn--secondary" onclick="_uninstallFromCatalog(\'' + _esc(m.name) + '\')">Uninstall</button>'
          : '<button class="action-btn" onclick="_installFromCatalog(\'' + _esc(m.name) + '\')">Install</button>';
        var tags = (m.tags || []).map(function(t) {
          return '<span class="tag-pill">' + _esc(t) + '</span>';
        }).join(' ');
        var homepage = m.homepage
          ? '<a href="' + _esc(m.homepage) + '" target="_blank" class="module-link">GitHub &#8599;</a>'
          : '';
        return '<div class="module-card">' +
          '<div class="module-card-header"><strong>' + _esc(m.name) + '</strong> ' + homepage + '</div>' +
          '<p class="module-desc">' + _esc(m.description) + '</p>' +
          '<div class="module-tags">' + tags + '</div>' +
          '<div class="module-action">' + actionBtn + '</div>' +
          '</div>';
      });
      grid.innerHTML = cards.join('');
    }
  }
  window._renderCatalog = _renderCatalog;

  function _loadCatalog() {
    fetch('/api/catalog')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var grid = document.getElementById('catalog-modules-grid');
        if (!grid) return;
        if (!data.modules || data.modules.length === 0) {
          grid.innerHTML = '<p class="empty-state">Catalog empty.</p>';
          return;
        }
        window._catalogModules = data.modules;
        // Wire up toolbar interactions
        var searchEl = document.getElementById('catalog-search');
        if (searchEl && !searchEl._pbgWired) {
          searchEl._pbgWired = true;
          searchEl.oninput = function() {
            window._catalogFilter.search = this.value.toLowerCase();
            _renderCatalog();
          };
        }
        var radios = document.querySelectorAll('input[name="catalog-installed-filter"]');
        radios.forEach(function(r) {
          if (!r._pbgWired) {
            r._pbgWired = true;
            r.onchange = function() {
              window._catalogFilter.installed = this.value;
              _renderCatalog();
            };
          }
        });
        _buildCatalogChips();
        _renderCatalog();
      })
      .catch(function(err) {
        var grid = document.getElementById('catalog-modules-grid');
        if (grid) grid.innerHTML = '<p class="empty-state" style="color:#c00">Catalog load failed: ' + _esc(String(err)) + '</p>';
      });
  }
  window._loadCatalog = _loadCatalog;

  // -------------------------------------------------------------------------
  // Install error rendering (v0.4.5)
  // -------------------------------------------------------------------------

  function _renderInstallError(json) {
    // Returns the alert text to show.
    if (json.diagnosis) {
      var d = json.diagnosis;
      return (
        "⚠ " + d.summary + "\n\n" +
        "→ " + d.suggestion + "\n\n" +
        "(error excerpt: " + (d.raw_excerpt || '').slice(0, 200) + "…)"
      );
    }
    return "Install failed:\n" + (json.error || 'unknown') + "\n\n" + (json.log || '').slice(0, 500);
  }

  function _installFromCatalog(name) {
    if (!confirm("Install '" + name + "' as a workstream commit?\n\nThis adds a submodule, pip installs the package, and appends it to pyproject.toml. Requires an active workstream.")) return;
    fetch('/api/catalog-install', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], json = parts[1];
        if (!ok) {
          alert(_renderInstallError(json));
          return;
        }
        var msg = "Installed " + name + ".\nCommit: " + (json.commit || 'n/a');
        alert(msg);
        window._registryLoaded = false;  // force registry reload on next switch
        fetch('/api/render', {method: 'POST'}).finally(function() {
          location.reload();
        });
      })
      .catch(function(err) {
        alert("Network error: " + String(err));
      });
  }
  window._installFromCatalog = _installFromCatalog;

  // -------------------------------------------------------------------------
  // Catalog uninstall (v0.5.5)
  // -------------------------------------------------------------------------

  function _uninstallFromCatalog(name) {
    if (!confirm('Uninstall "' + name + '"? This removes the package from the workspace venv, pyproject.toml, and workspace.yaml imports.')) return;
    fetch('/api/catalog-uninstall', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return {ok: r.ok, json: j}; }); })
      .then(function(p) {
        if (!p.ok) { alert('Uninstall failed: ' + (p.json.error || 'unknown')); return; }
        var msg = p.json.already_uninstalled ? 'Already uninstalled.' : 'Uninstalled ' + name + '.';
        if (p.json.branch) msg += '\n\nBranch: ' + p.json.branch + (p.json.commit ? ' (' + p.json.commit + ')' : '');
        alert(msg);
        if (typeof _loadCatalog === 'function') _loadCatalog();
        if (typeof _loadRegistry === 'function') _loadRegistry(true);
      })
      .catch(function(e) { alert('Network error: ' + e); });
  }
  window._uninstallFromCatalog = _uninstallFromCatalog;

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
          alert(_renderInstallError(json));
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
  // Workstream strip (v0.4.0b)
  // -------------------------------------------------------------------------

  function _refreshWorkStrip() {
    fetch('/api/work-status')
      .then(function(r){ return r.json(); })
      .then(_renderWorkStrip)
      .catch(function(err){ console.warn('work-status failed:', err); });
  }
  window._refreshWorkStrip = _refreshWorkStrip;

  function _renderWorkStrip(s) {
    var el = document.getElementById('workstream-strip');
    if (!el) return;
    if (!s.active) {
      el.classList.add('inactive');
      el.innerHTML =
        '<span class="ws-label">No active workstream.</span>' +
        '<button class="ws-btn ws-primary" onclick="_startWork()">Start workstream</button>';
      return;
    }
    el.classList.remove('inactive');
    var parts = [];
    parts.push('<span class="ws-label">Working on:</span>');
    parts.push('<code class="ws-branch">' + s.branch + '</code>');
    parts.push('<span class="ws-meta">' + s.commits_ahead + ' commit' + (s.commits_ahead === 1 ? '' : 's') + ' ahead of ' + s.base + '</span>');

    // No origin remote yet — surface the Create-GitHub-repo path instead of Push.
    if (s.has_origin === false) {
      if (s.gh_available === false) {
        parts.push('<span class="ws-warn" title="Install GitHub CLI to enable one-click repo creation">gh CLI missing</span>');
      } else {
        parts.push('<button class="ws-btn ws-primary" onclick="_createGithubRepo()" title="Create a GitHub repo for this workspace and push in one step">Create GitHub repo</button>');
      }
    } else {
      // Origin exists — normal Push / PR flow.
      if (s.unpushed > 0 || (!s.pushed && s.commits_ahead > 0)) {
        parts.push('<button class="ws-btn" onclick="_pushWork()">Push (' + s.unpushed + ')</button>');
      }
      if (s.pr_url) {
        parts.push('<a class="ws-link" href="' + s.pr_url + '" target="_blank">PR #' + s.pr_number + ' &#8599;</a>');
      } else if (s.pushed) {
        parts.push('<button class="ws-btn" onclick="_createPR()">Create PR</button>');
      }
    }

    parts.push('<button class="ws-btn ws-end" onclick="_endWork()" title="Switch back to ' + s.base + ' (workstream branch is preserved)">End</button>');
    el.innerHTML = parts.join(' ');
  }

  function _createGithubRepo() {
    openModal('modal-create-github-repo');
  }
  window._createGithubRepo = _createGithubRepo;

  function _submitCreateGithubRepo(form) {
    var data = {
      name: form.repo_name.value.trim(),
      visibility: form.visibility.value,
      description: form.description.value.trim() || null,
    };
    var errEl = form.querySelector('.form-error');
    errEl.textContent = '';
    fetch('/api/work-create-github-repo', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data),
    })
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        var ok = parts[0], json = parts[1];
        if (!ok) {
          var msg = json.error || 'unknown';
          if (json.diagnosis) msg += " — " + json.diagnosis.suggestion;
          errEl.textContent = msg;
          return;
        }
        closeModal('modal-create-github-repo');
        alert("Created " + json.visibility + " repo. Opening on GitHub...");
        if (json.repo_url) window.open(json.repo_url, '_blank');
        _refreshWorkStrip();
      });
  }
  window._submitCreateGithubRepo = _submitCreateGithubRepo;

  function _startWork() {
    var name = prompt("Workstream branch name (e.g., feat/baseline-work):");
    if (!name) return;
    fetch('/api/work-start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({branch: name.trim()}),
    })
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        if (!parts[0]) { alert("Could not start workstream:\n" + (parts[1].error || 'unknown')); return; }
        _refreshWorkStrip();
        location.reload();
      });
  }
  window._startWork = _startWork;

  function _pushWork() {
    fetch('/api/work-push', {method: 'POST'})
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        var ok = parts[0], json = parts[1];
        if (!ok) {
          var msg = "Push failed:\n" + (json.error || 'unknown');
          if (json.diagnosis) {
            msg = "⚠ " + json.diagnosis.summary + "\n→ " + json.diagnosis.suggestion;
          }
          alert(msg);
          _refreshWorkStrip();
          return;
        }
        alert("Pushed.");
        _refreshWorkStrip();
      });
  }
  window._pushWork = _pushWork;

  function _createPR() {
    openModal('modal-create-pr');
  }
  window._createPR = _createPR;

  function _submitCreatePR(form) {
    var data = {
      title: form.title.value.trim(),
      body: form.body.value.trim() || null,
    };
    var errEl = form.querySelector('.form-error');
    errEl.textContent = '';
    fetch('/api/work-create-pr', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data),
    })
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        var ok = parts[0], json = parts[1];
        if (!ok) {
          var msg = json.error || 'unknown';
          if (json.manual_url) msg += "\n\nOpen manually: " + json.manual_url;
          errEl.textContent = msg;
          return;
        }
        closeModal('modal-create-pr');
        window.open(json.pr_url, '_blank');
        _refreshWorkStrip();
      });
  }
  window._submitCreatePR = _submitCreatePR;

  // Generic Suggest button: writes a request, polls for response, fills the input.
  function _suggestInto(btn, kind, fieldName) {
    var form = btn.closest('form');
    var input = form.elements[fieldName];
    btn.disabled = true;
    btn.textContent = "…";
    fetch('/api/suggest', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({kind: kind}),
    })
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        var ok = parts[0], json = parts[1];
        if (!ok) { alert("Suggest request failed: " + (json.error || 'unknown')); btn.disabled = false; btn.textContent = "Suggest"; return; }
        var msg = json.instructions + "\n\nClick OK to start polling.";
        if (!confirm(msg)) { btn.disabled = false; btn.textContent = "Suggest"; return; }
        _pollSuggestion(json.id, input, btn, 0);
      });
  }
  window._suggestInto = _suggestInto;

  function _pollSuggestion(id, input, btn, attempts) {
    if (attempts > 90) {  // ~3 minutes
      btn.disabled = false; btn.textContent = "Suggest";
      alert("Timed out waiting for /pbg-suggest. Click Suggest again to retry.");
      return;
    }
    btn.textContent = "polling (" + attempts + ")";
    fetch('/api/suggest-poll?id=' + encodeURIComponent(id))
      .then(function(r){ return r.json(); })
      .then(function(json){
        if (json.ready) {
          input.value = json.suggestion;
          if (json.rationale) input.title = json.rationale;
          btn.disabled = false; btn.textContent = "Suggest";
          return;
        }
        setTimeout(function(){ _pollSuggestion(id, input, btn, attempts + 1); }, 2000);
      })
      .catch(function(){
        btn.disabled = false; btn.textContent = "Suggest";
      });
  }

  function _endWork() {
    if (!confirm("End workstream? This switches you back to base. Your branch is preserved.")) return;
    fetch('/api/work-end', {method: 'POST'})
      .then(function(r){ return r.json().then(function(j){ return [r.ok, j]; }); })
      .then(function(parts){
        if (!parts[0]) { alert("Could not end workstream:\n" + (parts[1].error || 'unknown')); return; }
        location.reload();
      });
  }
  window._endWork = _endWork;

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

  document.addEventListener("DOMContentLoaded", function () {
    // Initialize menu navigation.
    _initMenuNav();

    // Initialize workstream strip.
    _refreshWorkStrip();

    // Branches are now lazy-loaded when switching to the Branches tab.
    // (loadBranches() is called from _switchPage when pageId === 'branches'.)
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

  // -------------------------------------------------------------------------
  // Visualization lifecycle (v0.4.2)
  // -------------------------------------------------------------------------

  function _vizRefreshStatus(name) {
    fetch('/api/visualization-status?name=' + encodeURIComponent(name))
      .then(function(r) { return r.json(); })
      .then(function(s) {
        var el = document.getElementById('viz-status-' + name);
        if (!el) return;
        el.textContent = s.status;
        el.className = 'status-pill viz-status-' + s.status;
      });
  }
  function _vizRefreshAll() {
    document.querySelectorAll('[id^="viz-status-"]').forEach(function(el) {
      var name = el.id.substring('viz-status-'.length);
      _vizRefreshStatus(name);
    });
  }
  window._vizRefreshAll = _vizRefreshAll;

  function _vizCreate(name) {
    fetch('/api/visualization-create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(pair) {
        var ok = pair[0], json = pair[1];
        if (!ok) { alert('Create failed: ' + (json.error || 'unknown')); return; }
        var msg =
          'Request written to ' + json.request_path + '\n\n' +
          json.instructions + '\n\n' +
          "Click 'Refresh status' below when the skill finishes.";
        alert(msg);
        _vizPollUntilCreated(name, 0);
      });
  }
  window._vizCreate = _vizCreate;

  function _vizPollUntilCreated(name, attempts) {
    if (attempts > 60) return;  // ~2 minutes
    fetch('/api/visualization-status?name=' + encodeURIComponent(name))
      .then(function(r) { return r.json(); })
      .then(function(s) {
        _vizRefreshStatus(name);
        if (s.has_response) return;  // Done
        setTimeout(function() { _vizPollUntilCreated(name, attempts + 1); }, 2000);
      });
  }

  function _vizAddToProject(name) {
    fetch('/api/visualization-add-to-project', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(pair) {
        var ok = pair[0], json = pair[1];
        if (!ok) { alert('Add to project failed: ' + (json.error || 'unknown')); return; }
        _vizRefreshStatus(name);
      });
  }
  window._vizAddToProject = _vizAddToProject;

  function _vizCommit(names) {
    if (!confirm('Commit ' + names.length + ' visualization(s) to the active branch?')) return;
    fetch('/api/visualization-commit-batch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({names: names}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(pair) {
        var ok = pair[0], json = pair[1];
        if (!ok) { alert('Commit failed: ' + (json.error || 'unknown')); return; }
        alert('Committed: ' + (json.committed || []).join(', '));
        fetch('/api/render', {method: 'POST'}).finally(function() { location.reload(); });
      });
  }
  window._vizCommit = _vizCommit;

  function _vizCommitAll() {
    fetch('/api/visualization-commit-batch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(pair) {
        var ok = pair[0], json = pair[1];
        if (!ok) { alert('Commit-all failed: ' + (json.error || 'unknown')); return; }
        alert('Committed: ' + (json.committed || []).join(', '));
        fetch('/api/render', {method: 'POST'}).finally(function() { location.reload(); });
      });
  }
  window._vizCommitAll = _vizCommitAll;

  function _renderVizPreviewInModal(title, html, sourceUsed, notes) {
    var titleEl = document.getElementById('viz-preview-title');
    var srcEl = document.getElementById('viz-preview-source-row');
    var notesEl = document.getElementById('viz-preview-notes');
    var iframe = document.getElementById('viz-preview-iframe');
    if (titleEl) titleEl.textContent = 'Preview: ' + title;
    if (srcEl) srcEl.textContent = 'Source: ' + (sourceUsed || 'demo');
    if (notesEl) notesEl.textContent = notes || '';
    if (iframe) iframe.srcdoc = '<!DOCTYPE html><html><body style="margin:0;padding:8px">' + (html || '<p>(empty)</p>') + '</body></html>';
    openModal('modal-viz-preview');
  }

  function _vizPreview(name) {
    // Preview a registered workspace.yaml instance by name. The server
    // looks up its class+config and renders against demo data (or a real
    // investigation if source is set later via the modal).
    fetch('/api/visualization-preview-instance', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, source: 'demo'}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          alert(j.error || 'Preview failed');
          return;
        }
        _renderVizPreviewInModal(name, j.html, j.source_used, j.notes);
      });
  }
  window._vizPreview = _vizPreview;

  function _vizClassPreview(address, className) {
    // Preview a raw Visualization class (no config) against demo data.
    fetch('/api/visualization-preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address: address, source: 'demo'}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          alert(j.error || 'Preview failed');
          return;
        }
        _renderVizPreviewInModal(className + ' (demo)', j.html, j.source_used, j.notes);
      });
  }
  window._vizClassPreview = _vizClassPreview;

  function _vizRemove(name) {
    if (!confirm("Remove visualization '" + name + "'?")) return;
    fetch('/api/visualization', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(pair) {
        var ok = pair[0], json = pair[1];
        if (!ok) { alert('Remove failed: ' + (json.error || 'unknown')); return; }
        fetch('/api/render', {method: 'POST'}).finally(function() { location.reload(); });
      });
  }
  window._vizRemove = _vizRemove;

  // Auto-refresh viz statuses on page load
  window.addEventListener('DOMContentLoaded', function() { setTimeout(_vizRefreshAll, 200); });

  // ---------------------------------------------------------------------------
  // Composite explorer (v0.5.1)
  // ---------------------------------------------------------------------------

  window._ceCurrent = null;  // current composite + overrides state

  function _openCompositeExplorer(id) {
    // Navigate to the explorer as a normal tab (menu stays visible — user can
    // click another menu item to leave). The id lives in ?id= so deep-linking
    // / reload works; the hash drives which page is shown.
    var url = new URL(window.location.href);
    url.searchParams.set('id', id);
    url.hash = '#composite-explore';
    window.history.pushState({}, '', url.toString());
    _switchPage('composite-explore');
  }
  window._openCompositeExplorer = _openCompositeExplorer;

  function _initCompositeExplorer() {
    // Called when the explorer page is activated. Parses ?id=<spec_id> from
    // the URL, fetches the resolved composite, populates the page.
    var params = new URLSearchParams(window.location.search);
    var id = params.get('id');
    if (!id) {
      document.getElementById('ce-loading').textContent =
        'No composite id specified. Open via the Use button on a composite card.';
      return;
    }
    window._ceCurrent = {id: id, overrides: {}};
    // Eagerly populate the composite card cache so "Create simulation" can
    // open the Configure modal even when the user lands here directly
    // (deep-link / Use button) without ever visiting Simulation Setup.
    if (!window._compositesById || !window._compositesById[id]) {
      _loadComposites();
    }
    _ceFetch();
  }
  window._initCompositeExplorer = _initCompositeExplorer;

  function _ceSwitchTab(tab) {
    document.querySelectorAll('.ce-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.ce-tab-panel').forEach(function(p) {
      p.classList.toggle('active', p.dataset.tab === tab);
    });
    // Lazy-load each tab's content on first switch
    if (tab === 'history' && !window._ceHistoryLoaded) {
      window._ceHistoryLoaded = true;
      if (typeof _ceLoadHistory === 'function') _ceLoadHistory();
    }
    if (tab === 'compare' && window._ceCompareSet && window._ceCompareSet.size >= 2) {
      if (typeof _ceRenderCompare === 'function') _ceRenderCompare();
    }
    // Editor tabs (Tasks 4-6 supply the real renderers)
    if (tab === 'configure'     && typeof _ceRenderConfigure     === 'function') _ceRenderConfigure();
    if (tab === 'observables'   && typeof _ceRenderObservables   === 'function') _ceRenderObservables();
    if (tab === 'visualization' && typeof _ceRenderVisualization === 'function') _ceRenderVisualization();
  }
  window._ceSwitchTab = _ceSwitchTab;

  function _ceOpenPopout() {
    if (!window._ceCurrent || !window._ceCurrent.id) return;
    var url = location.pathname + '?focus=composite-explore&id=' +
              encodeURIComponent(window._ceCurrent.id);
    var w = window.open(url, '_blank', 'width=1200,height=900');
    if (!w) {
      // Popup blocked — same-tab fallback
      window.location.search = '?focus=composite-explore&id=' +
                                encodeURIComponent(window._ceCurrent.id);
    }
  }
  window._ceOpenPopout = _ceOpenPopout;

  // ─── History tab ──────────────────────────────────────────────────────
  window._ceRuns = {};            // run_id → run dict (cache)
  window._ceCompareSet = new Set();// selected run_ids for Compare

  function _ceLoadHistory() {
    if (window._ceHistoryFetching) return;
    window._ceHistoryFetching = true;
    var id = window._ceCurrent.id;
    fetch('/api/composite-runs?spec_id=' + encodeURIComponent(id))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var runs = data.runs || [];
        var body = document.getElementById('ce-history-body');
        var countBadge = document.getElementById('ce-history-count');
        if (countBadge) countBadge.textContent = '(' + runs.length + ')';
        if (!runs.length) {
          body.innerHTML = '<p class="empty-state">No runs yet — click <em>Test run</em> on the Wiring tab.</p>';
          window._ceHistoryFetching = false;
          return;
        }
        runs.forEach(function(r) { window._ceRuns[r.run_id] = r; });
        var rows = runs.map(_ceRenderHistoryRow).join('');
        body.innerHTML =
          '<table><thead><tr>' +
            '<th style="width:30px"></th><th>Label</th><th>Params</th>' +
            '<th>Started</th><th>Steps</th><th>Status</th><th></th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table>';
        window._ceHistoryFetching = false;
      })
      .catch(function(err) {
        var body = document.getElementById('ce-history-body');
        if (body) body.innerHTML = '<p style="color:#c00">Failed to load history: ' + _esc(String(err)) + '</p>';
        window._ceHistoryLoaded = false;
        window._ceHistoryFetching = false;
      });
  }
  window._ceLoadHistory = _ceLoadHistory;

  function _ceRenderHistoryRow(run) {
    var checked = window._ceCompareSet.has(run.run_id) ? 'checked' : '';
    var statusClass = ({completed: 'completed', running: 'running', failed: 'failed'})[run.status] || 'unknown';
    var paramStr = Object.keys(run.params || {})
      .map(function(k) { return k + '=' + run.params[k]; }).join(', ') || '—';
    var startedStr = new Date(run.started_at * 1000).toLocaleString();
    return '<tr>' +
      '<td><input type="checkbox" ' + checked +
        ' onchange="_ceToggleCompareSelection(\'' + _esc(run.run_id) + '\', this.checked)"></td>' +
      '<td>' + _esc(run.label || '') + '</td>' +
      '<td><code>' + _esc(paramStr) + '</code></td>' +
      '<td>' + _esc(startedStr) + '</td>' +
      '<td>' + (run.n_steps || 0) + '</td>' +
      '<td><span class="ce-history-status ' + statusClass + '">' + _esc(run.status) + '</span></td>' +
      '<td><button class="btn-mini" onclick="_ceViewRun(\'' + _esc(run.run_id) + '\')">View</button></td>' +
    '</tr>';
  }

  function _ceViewRun(run_id) {
    window._ceSelectedRunId = run_id;
    _ceSwitchTab('state');
    if (typeof _ceLoadState === 'function') _ceLoadState(run_id, 0);
  }
  window._ceViewRun = _ceViewRun;

  function _ceToggleCompareSelection(run_id, checked) {
    if (checked) window._ceCompareSet.add(run_id);
    else window._ceCompareSet.delete(run_id);
    var badge = document.getElementById('ce-compare-count');
    var tabBtn = document.querySelector('.ce-tab[data-tab="compare"]');
    var count = window._ceCompareSet.size;
    if (badge) badge.textContent = count > 0 ? '(' + count + ')' : '';
    if (tabBtn) tabBtn.style.display = count >= 2 ? '' : 'none';
  }
  window._ceToggleCompareSelection = _ceToggleCompareSelection;

  function _ceClearCompareSelection() {
    window._ceCompareSet.clear();
    document.querySelectorAll('input[type="checkbox"][onchange*="_ceToggleCompareSelection"]')
      .forEach(function(cb) { cb.checked = false; });
    _ceToggleCompareSelection('', false);  // refresh badge + tab visibility
  }
  window._ceClearCompareSelection = _ceClearCompareSelection;

  // ─── Compare tab ──────────────────────────────────────────────────────
  var _CE_COMPARE_PALETTE = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b',
                              '#8b5cf6', '#06b6d4', '#84cc16', '#ec4899'];

  function _ceRenderCompare() {
    var ids = Array.from(window._ceCompareSet);
    if (ids.length < 2) return;
    var body = document.getElementById('ce-compare-body');
    body.innerHTML = '<p class="empty-state">Loading&hellip;</p>';
    Promise.all(ids.map(function(id) {
      return fetch('/api/composite-run/' + encodeURIComponent(id))
        .then(function(r) { return r.json(); });
    })).then(function(results) {
      var runs = ids.map(function(id, i) {
        return { run_id: id, meta: window._ceRuns[id] || {},
                  trajectory: results[i].trajectory || [],
                  color: _CE_COMPARE_PALETTE[i % _CE_COMPARE_PALETTE.length] };
      });

      // Find observable keys (numeric leaves) across all trajectories
      var observables = {};
      runs.forEach(function(run) {
        run.trajectory.forEach(function(point) {
          Object.keys(point.state || {}).forEach(function(k) {
            var v = point.state[k];
            if (typeof v === 'number') observables[k] = true;
          });
        });
      });
      var obsList = Object.keys(observables);

      // Legend
      var legend = '<div class="ce-compare-legend">' + runs.map(function(run) {
        return '<span><span class="swatch" style="background:' + run.color + '"></span>' +
                _esc(run.meta.label || run.run_id.slice(-12)) + '</span>';
      }).join('') + '</div>';

      // One chart div per observable
      var chartContainers = obsList.map(function(k) {
        return '<div id="ce-cmp-' + _esc(k) + '" style="height:280px;margin-bottom:12px"></div>';
      }).join('');

      // Param diff table
      var allKeys = new Set();
      runs.forEach(function(run) {
        Object.keys(run.meta.params || {}).forEach(function(k) { allKeys.add(k); });
      });
      var paramKeys = Array.from(allKeys);
      var diffHead = '<tr><th>parameter</th>' + runs.map(function(run) {
        return '<th style="border-bottom:3px solid ' + run.color + '">' +
                _esc(run.meta.label || run.run_id.slice(-12)) + '</th>';
      }).join('') + '</tr>';
      var diffRows = paramKeys.map(function(k) {
        var values = runs.map(function(run) { return (run.meta.params || {})[k]; });
        var uniq = new Set(values.map(function(v) { return JSON.stringify(v); }));
        var differs = uniq.size > 1;
        return '<tr><td><code>' + _esc(k) + '</code></td>' +
                values.map(function(v) {
                  return '<td' + (differs ? ' class="differs"' : '') + '>' +
                          _esc(String(v === undefined ? '—' : v)) + '</td>';
                }).join('') + '</tr>';
      }).join('');
      var diffTable = '<table class="ce-diff-table"><thead>' + diffHead +
                      '</thead><tbody>' + diffRows + '</tbody></table>';

      body.innerHTML = legend + chartContainers + diffTable;

      // Plot each observable
      obsList.forEach(function(k) {
        var traces = runs.map(function(run) {
          var times = run.trajectory.map(function(p) { return p.time; });
          var ys = run.trajectory.map(function(p) { return p.state[k]; });
          return { x: times, y: ys, type: 'scatter', mode: 'lines',
                    name: run.meta.label || run.run_id.slice(-12),
                    line: { color: run.color, width: 2 } };
        });
        Plotly.newPlot('ce-cmp-' + _esc(k), traces, {
          title: { text: k, font: { size: 13 } },
          margin: { l: 55, r: 15, t: 35, b: 40 },
          showlegend: false,
        }, { responsive: true, displayModeBar: false });
      });
    }).catch(function(err) {
      body.innerHTML = '<span style="color:#c00">Failed to fetch runs: ' + _esc(String(err)) + '</span>';
    });
  }
  window._ceRenderCompare = _ceRenderCompare;

  // ─── State tab ────────────────────────────────────────────────────────
  window._ceTrajectoryCache = {};  // run_id → trajectory array

  function _ceLoadState(run_id, step) {
    var cached = window._ceTrajectoryCache[run_id];
    if (cached) {
      _ceShowState(run_id, step, cached);
      return;
    }
    fetch('/api/composite-run/' + encodeURIComponent(run_id))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var trajectory = data.trajectory || [];
        window._ceTrajectoryCache[run_id] = trajectory;
        _ceShowState(run_id, step, trajectory);
      })
      .catch(function(err) {
        var tree = document.getElementById('ce-state-tree');
        if (tree) tree.innerHTML = '<span style="color:#c00">Failed to fetch run: ' + _esc(String(err)) + '</span>';
      });
  }
  window._ceLoadState = _ceLoadState;

  function _ceShowState(run_id, step, trajectory) {
    var ctrls = document.getElementById('ce-state-controls');
    var tree = document.getElementById('ce-state-tree');
    var actions = document.getElementById('ce-state-actions');
    if (!trajectory.length) {
      ctrls.innerHTML = '<p class="empty-state">No state recorded for this run.</p>';
      tree.innerHTML = '';
      actions.style.display = 'none';
      return;
    }
    var maxStep = trajectory.length - 1;
    var safeStep = Math.max(0, Math.min(step, maxStep));
    ctrls.innerHTML =
      '<label>run: <code>' + _esc(run_id) + '</code></label>' +
      '<br><label>step: <input type="range" id="ce-state-slider" min="0" max="' +
        maxStep + '" value="' + safeStep + '"' +
        ' oninput="_ceShowState(\'' + _esc(run_id) + '\', parseInt(this.value), window._ceTrajectoryCache[\'' + _esc(run_id) + '\'])"></label> ' +
      '<span id="ce-state-step-val">step ' + safeStep + ' of ' + maxStep + '</span>';
    document.getElementById('ce-state-step-label').textContent = safeStep;
    var pt = trajectory[safeStep];
    tree.innerHTML = '';
    _ceRenderStateTree(pt && pt.state || {}, tree, 0);
    actions.style.display = '';
    window._ceCurrentStateForSnapshot = pt && pt.state || {};
  }
  window._ceShowState = _ceShowState;

  function _ceRenderStateTree(obj, container, depth) {
    var node = _ceRenderJSON(obj, depth);
    if (typeof node === 'string') container.innerHTML = node;
    else { container.innerHTML = ''; container.appendChild(node); }
  }
  window._ceRenderStateTree = _ceRenderStateTree;

  function _ceRenderJSON(obj, depth) {
    if (obj === null) return '<span class="ce-jt-null">null</span>';
    if (typeof obj === 'boolean') return '<span class="ce-jt-bool">' + obj + '</span>';
    if (typeof obj === 'number') return '<span class="ce-jt-num">' + obj + '</span>';
    if (typeof obj === 'string') return '<span class="ce-jt-str">"' + _esc(obj) + '"</span>';
    if (Array.isArray(obj)) {
      if (obj.length === 0) return '<span class="ce-jt-bracket">[]</span>';
      if (depth >= 5) return '<span class="ce-jt-bracket">[…' + obj.length + ' items]</span>';
      var id = 'ce-jt-' + Math.random().toString(36).slice(2, 9);
      var html = '<span class="ce-jt-toggle" onclick="_ceToggleJt(\'' + id + '\')">&blacktriangledown;</span>';
      html += '<span class="ce-jt-bracket">[</span><span style="color:#94a3b8;font-size:0.85em"> ' + obj.length + ' items</span>';
      html += '<div id="' + id + '" style="margin-left:1.2em">';
      obj.forEach(function(v, i) {
        html += '<div>' + _ceRenderJSON(v, depth + 1) + (i < obj.length - 1 ? ',' : '') + '</div>';
      });
      html += '</div><span class="ce-jt-bracket">]</span>';
      return html;
    }
    if (typeof obj === 'object') {
      var keys = Object.keys(obj);
      if (keys.length === 0) return '<span class="ce-jt-bracket">{}</span>';
      if (depth >= 5) return '<span class="ce-jt-bracket">{…' + keys.length + ' keys}</span>';
      var id = 'ce-jt-' + Math.random().toString(36).slice(2, 9);
      var html = '<span class="ce-jt-toggle" onclick="_ceToggleJt(\'' + id + '\')">&blacktriangledown;</span>';
      html += '<span class="ce-jt-bracket">{</span>';
      html += '<div id="' + id + '" style="margin-left:1.2em">';
      keys.forEach(function(k, i) {
        html += '<div><span class="ce-jt-key">' + _esc(k) + '</span>: ' +
                _ceRenderJSON(obj[k], depth + 1) + (i < keys.length - 1 ? ',' : '') + '</div>';
      });
      html += '</div><span class="ce-jt-bracket">}</span>';
      return html;
    }
    return String(obj);
  }

  function _ceToggleJt(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('ce-jt-collapsed');
  }
  window._ceToggleJt = _ceToggleJt;

  // ─── Snapshot to initial ──────────────────────────────────────────────
  function _ceSnapshotToInitial() {
    var state = window._ceCurrentStateForSnapshot || {};
    var paramInputs = document.querySelectorAll('#ce-parameters input[data-param]');
    var matched = [], skipped = [];
    function walk(obj, prefix) {
      Object.keys(obj || {}).forEach(function(k) {
        var v = obj[k];
        var path = prefix ? prefix + '.' + k : k;
        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
          walk(v, path);
        } else {
          // Try to find a parameter input whose name matches the leaf key
          var target = null;
          paramInputs.forEach(function(inp) {
            if (inp.dataset.param === k) target = inp;
          });
          if (!target) {
            skipped.push({ path: path, reason: 'no matching parameter' });
            return;
          }
          var declaredType = target.dataset.type;
          var ok = (declaredType === 'float' && typeof v === 'number')
                || (declaredType === 'int'   && typeof v === 'number' && Number.isInteger(v))
                || (declaredType === 'string' && typeof v === 'string')
                || (declaredType === 'bool'  && typeof v === 'boolean');
          if (!ok) {
            skipped.push({ path: path, reason: 'type mismatch (' + declaredType + ' vs ' + typeof v + ')' });
            return;
          }
          target.value = v;
          matched.push({ path: path, value: v });
        }
      });
    }
    walk(state, '');
    var report = document.getElementById('ce-snapshot-report');
    var skippedHtml = skipped.length
      ? '<details style="margin-top:4px"><summary>Show ' + skipped.length + ' skipped</summary><ul style="font-size:0.85em">' +
          skipped.map(function(s) { return '<li><code>' + _esc(s.path) + '</code> — ' + _esc(s.reason) + '</li>'; }).join('') +
        '</ul></details>'
      : '';
    report.innerHTML = 'Mapped ' + matched.length + ' of ' +
                       (matched.length + skipped.length) + ' leaves. ' + skippedHtml;
    _ceSwitchTab('wiring');
  }
  window._ceSnapshotToInitial = _ceSnapshotToInitial;

  function _ceFetch() {
    var url = '/api/composite-resolve?id=' + encodeURIComponent(window._ceCurrent.id) +
      '&overrides=' + encodeURIComponent(JSON.stringify(window._ceCurrent.overrides));
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) {
          document.getElementById('ce-loading').innerHTML =
            '<span style="color:#c00">Error: ' + _esc(data.error) + '</span>';
          return;
        }
        document.getElementById('ce-loading').style.display = 'none';
        document.getElementById('ce-main').style.display = '';
        document.getElementById('ce-name').textContent = data.name;
        document.getElementById('ce-description').textContent = data.description || '';
        document.getElementById('ce-id').textContent = data.id;
        window._ceCurrent.parameters = data.parameters;
        // Populate in-memory doc for editor tabs
        window._composeDoc = data.state;
        window._composeDocSourceRef = data.id;
        // Send wiring state to loom-explore iframe via postMessage
        _loadCompositeExplorer(data.id, data.state, data.name);
        // Render parameter editor
        _ceRenderParameters(data.parameters);
        // Render default (configure) editor tab
        if (typeof _ceRenderConfigure === 'function') _ceRenderConfigure();
        // Render state JSON
        document.getElementById('ce-state-json').textContent =
          JSON.stringify(data.state, null, 2);
      })
      .catch(function(err) {
        document.getElementById('ce-loading').innerHTML =
          '<span style="color:#c00">Network error: ' + _esc(String(err)) + '</span>';
      });
  }

  function _legacyLoadCompositeSvg(ref) {
    var el = document.getElementById('composite-explore-svg-legacy');
    if (!el) return;
    el.innerHTML = '<p style="color:#888">Loading SVG…</p>';
    fetch('/api/composite-resolve?id=' + encodeURIComponent(ref))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.svg) {
          el.innerHTML = data.svg;
        } else {
          el.innerHTML = '<p style="color:#666">No SVG returned from legacy render.</p>';
        }
      })
      .catch(function() {
        el.innerHTML = '<p style="color:#666">Legacy SVG render unavailable.</p>';
      });
  }

  // _loadCompositeExplorer: send composite state to the loom-explore iframe.
  // Can be called with a pre-resolved state object (from _ceFetch) or with
  // just a ref string, in which case it fetches /api/composite-state first.
  // When ui.composite_view === 'bigraph-viz', uses the legacy SVG path instead.
  function _loadCompositeExplorer(ref, stateObj, nameHint) {
    // Apply visibility toggle each time the explorer is loaded (catches cases
    // where the config fetch completed after the first render).
    _applyCompositeViewMode();

    var cfg = window._uiConfig || {};
    if ((cfg.composite_view || 'loom-explore') === 'bigraph-viz') {
      _legacyLoadCompositeSvg(ref);
      return;
    }

    var iframe = document.getElementById('composite-explore-frame');
    if (!iframe) return;

    function _postState(state, name) {
      var post = function() {
        iframe.contentWindow.postMessage({
          type: 'composite:load',
          state: state,
          metadata: { name: name || ref },
        }, '*');
      };
      if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
        post();
      } else {
        var listener = function(ev) {
          if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
            window._loomExploreReady = window._loomExploreReady || {};
            window._loomExploreReady[iframe.id] = true;
            window.removeEventListener('message', listener);
            post();
          }
        };
        window.addEventListener('message', listener);
      }
    }

    if (stateObj !== undefined) {
      // Caller already has the resolved state (e.g. from _ceFetch via composite-resolve)
      _postState(stateObj, nameHint || ref);
    } else {
      // Fetch state independently via /api/composite-state
      fetch('/api/composite-state?ref=' + encodeURIComponent(ref))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.error) {
            console.error('composite-state error:', data.error);
            return;
          }
          _postState(data.state, nameHint || ref);
        })
        .catch(function(err) { console.error('composite load failed:', err); });
    }
  }
  window._loadCompositeExplorer = _loadCompositeExplorer;

  /* ── In-memory composite document (Task 3) ──────────────────────────────
     Populated by _ceFetch; mutated by editor tab renderers (Tasks 4-6).
     Tasks 4-6 replace the stub renderers below with real implementations. */
  window._composeDoc = null;
  window._composeDocSourceRef = null;

  /** Post the current in-memory doc to the loom iframe so wiring re-renders. */
  function _cePushDocToLoom() {
    var iframe = document.getElementById('composite-explore-frame');
    if (!iframe || !window._composeDoc) return;
    var post = function() {
      iframe.contentWindow.postMessage({
        type: 'composite:load',
        state: window._composeDoc,
        metadata: { name: window._composeDocSourceRef || 'edited' },
      }, '*');
    };
    if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
      post();
    } else {
      var listener = function(ev) {
        if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
          window._loomExploreReady = window._loomExploreReady || {};
          window._loomExploreReady[iframe.id] = true;
          window.removeEventListener('message', listener);
          post();
        }
      };
      window.addEventListener('message', listener);
    }
  }
  window._cePushDocToLoom = _cePushDocToLoom;

  /** Stub renderers — replaced by Tasks 4-6 when those tasks land. */
  function _ceRenderConfigure() {
    var panel = document.getElementById('ce-panel-configure');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/composite-process-configs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ document: window._composeDoc }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        var rows = data.rows || [];
        if (rows.length === 0) {
          panel.innerHTML = '<p class="empty-state">No processes in this composite.</p>';
          return;
        }
        panel.innerHTML = rows.map(function(row) {
          var configs = (row.configs || []).map(function(c) {
            var inputType = typeof c.value;
            var inputAttr, valAttr;
            if (inputType === 'number') {
              inputAttr = 'type="number" step="any"';
              valAttr = 'value="' + _esc(String(c.value)) + '"';
            } else if (inputType === 'boolean') {
              inputAttr = 'type="checkbox"' + (c.value ? ' checked' : '');
              valAttr = '';
            } else {
              inputAttr = 'type="text"';
              valAttr = 'value="' + _esc(String(c.value == null ? '' : c.value)) + '"';
            }
            var unitsBadge = c.units
              ? '<span style="color:#888;font-size:0.8em;margin-left:6px">[' + _esc(String(c.units)) + ']</span>'
              : '';
            var defStr = (c.default !== undefined)
              ? ('default: ' + _esc(JSON.stringify(c.default)))
              : '';
            return '<div style="display:grid;grid-template-columns:160px 1fr 200px;gap:8px;padding:4px 0;align-items:center">' +
                   '<code>' + _esc(c.key) + '</code>' +
                   '<input ' + inputAttr + ' ' + valAttr +
                       ' onchange="_ceUpdateConfig(\'' + _esc(row.name) + '\',\'' + _esc(c.key) + '\',this)">' +
                   '<small style="color:#888">' + defStr + unitsBadge + '</small>' +
                   '</div>';
          }).join('');
          return '<details open style="margin-bottom:10px;border:1px solid #e5e7eb;border-radius:4px;padding:8px">' +
                 '<summary style="cursor:pointer;font-weight:600">' +
                 _esc(row.name) +
                 ' <small style="color:#666;font-weight:normal">(' + _esc(row.address) + ')</small>' +
                 '</summary>' +
                 '<div style="margin-top:8px">' + configs + '</div>' +
                 '</details>';
        }).join('');
      })
      .catch(function(err) {
        panel.innerHTML = '<p style="color:#991b1b">Failed to load configs: ' + _esc(String(err)) + '</p>';
      });
  }
  window._ceRenderConfigure = _ceRenderConfigure;

  function _ceUpdateConfig(processName, key, inputEl) {
    if (!window._composeDoc) return;
    var raw = inputEl.type === 'checkbox' ? inputEl.checked : inputEl.value;
    // Best-effort type coercion based on the input element's type attribute
    var value;
    if (inputEl.type === 'number') {
      value = parseFloat(raw);
      if (isNaN(value)) value = raw;
    } else if (inputEl.type === 'checkbox') {
      value = !!raw;
    } else {
      value = raw;
    }
    var state = window._composeDoc.state || {};
    var proc = state[processName];
    if (!proc || !proc.config) {
      console.warn('process not found:', processName);
      return;
    }
    proc.config[key] = value;
    _cePushDocToLoom();  // wiring view doesn't change for config edits, but cheap to keep in sync
  }
  window._ceUpdateConfig = _ceUpdateConfig;

  function _ceRenderObservables() {
    var panel = document.getElementById('ce-panel-observables');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/composite-state-tree-doc', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ document: window._composeDoc }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        var leaves = (data.nodes || []).filter(function(n) { return n.kind === 'store'; });
        var existingEmitter = (window._composeDoc.state || {}).emitter;
        var selected = new Set();
        if (existingEmitter && existingEmitter.inputs) {
          Object.values(existingEmitter.inputs).forEach(function(p) {
            selected.add((p || []).join('.'));
          });
        }
        var useRam = !!(existingEmitter && existingEmitter.address === 'local:RAMEmitter');
        var rows = leaves.map(function(n) {
          var key = (n.path || []).join('.');
          var checked = selected.has(key) ? ' checked' : '';
          var typeStr = n.type || '';
          var defStr = (n.default !== undefined)
            ? '  default: ' + _esc(JSON.stringify(n.default))
            : '';
          return '<div style="padding:3px 0"><label>' +
                 '<input type="checkbox" data-path="' + _esc(key) + '"' + checked +
                       ' onchange="_ceObservablesChanged()"> ' +
                 '<code>' + _esc(key) + '</code> ' +
                 '<small style="color:#888">' + _esc(typeStr) + defStr + '</small>' +
                 '</label></div>';
        }).join('');
        panel.innerHTML =
          '<p class="panel-lead" style="margin-bottom:8px">Tick paths to wire an inline emitter into the composite. Untick everything to strip the emitter.</p>' +
          '<label style="margin-bottom:8px;display:block"><input type="checkbox" id="ce-use-ram"' +
          (useRam ? ' checked' : '') +
          ' onchange="_ceObservablesChanged()"> ' +
          'Use <code>RAMEmitter</code> (default: <code>SQLiteEmitter</code>)</label>' +
          (rows || '<p class="empty-state">No leaf stores found.</p>');
      })
      .catch(function(err) {
        panel.innerHTML = '<p style="color:#991b1b">Failed to load state tree: ' + _esc(String(err)) + '</p>';
      });
  }
  window._ceRenderObservables = _ceRenderObservables;

  function _ceObservablesChanged() {
    if (!window._composeDoc) return;
    var panel = document.getElementById('ce-panel-observables');
    var paths = [];
    panel.querySelectorAll('input[type=checkbox][data-path]:checked').forEach(function(cb) {
      paths.push(cb.dataset.path.split('.'));
    });
    var useRam = !!(document.getElementById('ce-use-ram') || {}).checked;
    fetch('/api/compose-doc-inject-emitter', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document: window._composeDoc,
        paths: paths,
        address: useRam ? 'local:RAMEmitter' : 'local:SQLiteEmitter',
      }),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.document) {
          window._composeDoc = data.document;
          _cePushDocToLoom();
        }
      })
      .catch(function(err) { console.error('inject emitter failed:', err); });
  }
  window._ceObservablesChanged = _ceObservablesChanged;

  function _ceRenderVisualization() {
    var panel = document.getElementById('ce-panel-visualization');
    if (!panel) return;
    if (!window._composeDoc) {
      panel.innerHTML = '<p class="empty-state">No composite loaded.</p>';
      return;
    }
    fetch('/api/visualization-classes')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var classes = data.classes || [];
        var currentViz = (window._composeDoc.state || {}).viz;
        var currentClass = '';
        if (currentViz && currentViz.address) {
          currentClass = (currentViz.address.split(':')[1] || '').split('.').pop();
        }
        var currentCfgStr = (currentViz && currentViz.config)
          ? JSON.stringify(currentViz.config, null, 2) : '{}';
        var emitterPorts = Object.keys(((window._composeDoc.state || {}).emitter || {}).inputs || {});
        var optionsHtml = '<option value="">— pick a Visualization class —</option>' +
                          classes.map(function(c) {
                            var sel = (c.name === currentClass) ? ' selected' : '';
                            var doc = c.doc ? ' — ' + _esc(c.doc) : '';
                            return '<option value="' + _esc(c.name) + '"' + sel + '>' +
                                   _esc(c.name) + doc + '</option>';
                          }).join('');
        var portsHint = emitterPorts.length
          ? emitterPorts.map(function(p) { return '<code>' + _esc(p) + '</code>'; }).join(', ')
          : '<em>none — add observables first</em>';
        panel.innerHTML =
          '<label>Visualization class' +
          '<select id="ce-viz-class" onchange="_ceVizChanged()">' + optionsHtml + '</select>' +
          '</label>' +
          '<label>Config (JSON)' +
          '<textarea id="ce-viz-config" rows="4" onchange="_ceVizChanged()">' +
          _esc(currentCfgStr) + '</textarea>' +
          '</label>' +
          '<p style="font-size:0.85em;color:#555;margin:8px 0">' +
          'Auto-wire: viz inputs that match these emitter ports will be connected: ' +
          portsHint + '</p>' +
          '<button class="btn-mini" onclick="_ceVizRemove()" style="margin-top:8px">Remove visualization</button>';
      })
      .catch(function(err) {
        panel.innerHTML = '<p style="color:#991b1b">Failed to load Viz classes: ' + _esc(String(err)) + '</p>';
      });
  }
  window._ceRenderVisualization = _ceRenderVisualization;

  function _ceVizChanged() {
    if (!window._composeDoc) return;
    var className = (document.getElementById('ce-viz-class') || {}).value || '';
    var configRaw = (document.getElementById('ce-viz-config') || {}).value || '{}';
    var config;
    try { config = JSON.parse(configRaw); }
    catch (e) { console.warn('viz config JSON parse:', e); return; }
    if (!className) {
      // Strip viz
      fetch('/api/compose-doc-strip-viz', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ document: window._composeDoc }),
      }).then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.document) { window._composeDoc = data.document; _cePushDocToLoom(); }
        });
      return;
    }
    // Fetch the class's declared inputs() for auto-wire
    fetch('/api/visualization-class-inputs?name=' + encodeURIComponent(className))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var vizInputs = data.inputs || {};
        return fetch('/api/compose-doc-inject-viz', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            document: window._composeDoc,
            class_name: className,
            viz_inputs: vizInputs,
            config: config,
          }),
        });
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.document) {
          window._composeDoc = data.document;
          _cePushDocToLoom();
          // Re-render the hint line in case emitter ports changed in between
          // (no full re-render to preserve current input focus).
        }
      })
      .catch(function(err) { console.error('viz inject failed:', err); });
  }
  window._ceVizChanged = _ceVizChanged;

  function _ceVizRemove() {
    var sel = document.getElementById('ce-viz-class');
    if (sel) sel.value = '';
    _ceVizChanged();
  }
  window._ceVizRemove = _ceVizRemove;

  function _ceOpenSaveModal() {
    if (!window._composeDoc) {
      alert('No composite to save.');
      return;
    }
    var sel = document.getElementById('ce-save-investigation');
    if (!sel) return;
    sel.innerHTML = '<option value="">— pick an investigation —</option>';
    var srcEl = document.getElementById('ce-save-source-ref');
    if (srcEl) {
      srcEl.innerHTML = window._composeDocSourceRef
        ? 'Source: <code>' + _esc(window._composeDocSourceRef) + '</code>'
        : '';
    }
    var errEl = document.querySelector('#form-ce-save .form-error');
    if (errEl) errEl.textContent = '';
    fetch('/api/investigations').then(function(r) { return r.json(); })
      .then(function(data) {
        (data.investigations || []).forEach(function(inv) {
          var opt = document.createElement('option');
          opt.value = inv.name;
          opt.textContent = inv.name;
          sel.appendChild(opt);
        });
        openModal('modal-ce-save');
      })
      .catch(function(err) {
        if (errEl) errEl.textContent = 'Failed to load investigations: ' + String(err);
        openModal('modal-ce-save');
      });
  }
  window._ceOpenSaveModal = _ceOpenSaveModal;

  function _ceSubmitSave(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    if (!window._composeDoc) {
      if (errEl) errEl.textContent = 'No composite loaded.';
      return;
    }
    var payload = {
      investigation: data.get('investigation'),
      name: data.get('name'),
      document: window._composeDoc,
      source_ref: window._composeDocSourceRef || '',
    };
    if (!payload.investigation) {
      if (errEl) errEl.textContent = 'Pick an investigation.';
      return;
    }
    fetch('/api/investigation-composite-save-sidecar', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'save failed';
          return;
        }
        closeModal('modal-ce-save');
        // Nav to investigation Composites tab; reuse the existing helper if available.
        window.location.hash = '#investigations';
        if (typeof _openInvestigation === 'function') {
          _openInvestigation(payload.investigation);
        }
      });
  }
  window._ceSubmitSave = _ceSubmitSave;

  function _ceRenderParameters(params) {
    var container = document.getElementById('ce-parameters');
    var keys = Object.keys(params || {});
    if (!keys.length) {
      container.innerHTML = '<p class="muted">No parameters.</p>';
      return;
    }
    container.innerHTML = keys.map(function(k) {
      var pdef = params[k];
      var def = pdef.default;
      var current = (window._ceCurrent.overrides && window._ceCurrent.overrides[k] !== undefined)
        ? window._ceCurrent.overrides[k] : def;
      var type = pdef.type || 'string';
      var inputType = (type === 'int' || type === 'float') ? 'number' : 'text';
      var step = (type === 'float') ? 'any' : (type === 'int' ? '1' : '');
      var desc = pdef.description
        ? '<div class="ce-param-desc muted"><small>' + _esc(pdef.description) + '</small></div>'
        : '';
      return '<div class="ce-param-row">' +
        '<label class="ce-param-label">' +
          '<span class="ce-param-name"><code>' + _esc(k) + '</code> ' +
            '<span class="muted">(' + _esc(type) + ')</span></span>' +
          '<input class="ce-param-input" data-param="' + _esc(k) +
            '" data-type="' + _esc(type) + '" type="' + inputType + '"' +
            (step ? ' step="' + step + '"' : '') +
            ' value="' + _esc(String(current !== undefined && current !== null ? current : '')) + '">' +
        '</label>' +
        desc +
      '</div>';
    }).join('');
  }

  function _ceCollectOverrides() {
    var inputs = document.querySelectorAll('#ce-parameters input[data-param]');
    var out = {};
    inputs.forEach(function(el) {
      var k = el.dataset.param, t = el.dataset.type;
      var v = el.value;
      if (v === '') return;
      if (t === 'float') v = parseFloat(v);
      else if (t === 'int') v = parseInt(v, 10);
      else if (t === 'bool') v = (v === 'true' || v === '1');
      out[k] = v;
    });
    return out;
  }

  function _ceUpdateDiagram() {
    window._ceCurrent.overrides = _ceCollectOverrides();
    document.getElementById('ce-diagram').innerHTML = '<p class="empty-state">Re-rendering diagram&hellip;</p>';
    _ceFetch();
  }
  window._ceUpdateDiagram = _ceUpdateDiagram;

  function _ceTestRun() {
    var steps = parseInt(document.getElementById('ce-steps').value, 10) || 5;
    var overrides = _ceCollectOverrides();
    var resultsEl = document.getElementById('ce-test-results');
    resultsEl.innerHTML = '<p class="empty-state">Running&hellip;</p>';
    fetch('/api/composite-test-run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: window._ceCurrent.id, overrides: overrides, steps: steps}),
    })
      .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], json = parts[1];
        if (!ok) {
          var msg = '<span style="color:#c00"><strong>Test run failed:</strong> ' +
            _esc(json.error || 'unknown') + '</span>';
          if (json.traceback) {
            msg += '<details><summary>traceback</summary><pre style="font-size:0.8em">' +
              _esc(json.traceback) + '</pre></details>';
          }
          resultsEl.innerHTML = msg;
          return;
        }
        // Show first few entries per emitter
        var resultsHtml = '<p><strong>Completed ' + json.steps + ' steps.</strong></p>';
        var keys = Object.keys(json.results || {});
        if (!keys.length) {
          resultsHtml += '<p class="muted">(No emitters produced output.)</p>';
        } else {
          resultsHtml += keys.map(function(k) {
            var entries = json.results[k];
            var rows = entries.slice(0, 10).map(function(e, i) {
              return '<tr><td>' + i + '</td><td><code>' + _esc(JSON.stringify(e)) + '</code></td></tr>';
            }).join('');
            return '<h4>' + _esc(k) + ' (' + entries.length + ' entries)</h4>' +
              '<table style="font-size:0.85em"><thead><tr><th>Step</th><th>Value</th></tr></thead><tbody>' +
              rows + '</tbody></table>';
          }).join('');
        }
        resultsEl.innerHTML = resultsHtml;
        // Persist + refresh history
        window._ceHistoryLoaded = false;  // force re-fetch on next visit
        if (document.querySelector('.ce-tab-panel[data-tab="history"]') &&
            document.querySelector('.ce-tab-panel[data-tab="history"]').classList.contains('active')) {
          _ceLoadHistory();
        }
      })
      .catch(function(err) {
        resultsEl.innerHTML = '<span style="color:#c00">Network error: ' + _esc(String(err)) + '</span>';
      });
  }
  window._ceTestRun = _ceTestRun;

  function _cePromoteSimulation() {
    // Re-use the existing _useComposite flow (Configure modal) with current overrides pre-applied.
    var id = window._ceCurrent.id;

    function _openModalAndApplyOverrides() {
      _useComposite(id);
      var modal = document.getElementById('modal-configure-composite');
      if (modal) {
        Object.keys(window._ceCurrent.overrides || {}).forEach(function(k) {
          var inp = modal.querySelector('input[name="param_' + k + '"]');
          if (inp) inp.value = window._ceCurrent.overrides[k];
        });
      }
    }

    if ((window._compositesById || {})[id]) {
      _openModalAndApplyOverrides();
      return;
    }
    // Cache not populated yet (user landed here without visiting
    // Simulation Setup). Fetch synchronously-as-possible, then open.
    fetch('/api/composites')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var composites = data.composites || [];
        window._compositesById = window._compositesById || {};
        composites.forEach(function(c) { window._compositesById[c.id] = c; });
        if (!window._compositesById[id]) {
          alert('Composite "' + id + '" not found on the server. It may have been removed.');
          return;
        }
        _openModalAndApplyOverrides();
      })
      .catch(function(err) {
        alert('Failed to load composites: ' + err);
      });
  }
  window._cePromoteSimulation = _cePromoteSimulation;

  // ─── Investigations tab (v0.5.0) ──────────────────────────────────────
  window._investigations = [];
  window._investigationsFilter = { search: '', tags: new Set() };
  window._investigationsView = 'grid';

  function _loadInvestigations() {
    fetch('/api/investigations')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        window._investigations = data.investigations || [];
        _buildInvestigationTagChips();
        _renderInvestigations();
      })
      .catch(function(err) {
        var grid = document.getElementById('investigations-grid');
        if (grid) grid.innerHTML = '<p style="color:#c00">Failed to load: ' + _esc(String(err)) + '</p>';
      });
  }
  window._loadInvestigations = _loadInvestigations;

  function _buildInvestigationTagChips() {
    var container = document.getElementById('investigations-tag-chips');
    if (!container) return;
    var tags = new Set();
    window._investigations.forEach(function(inv) {
      (inv.tags || []).forEach(function(t) { tags.add(t); });
    });
    var chips = Array.from(tags).sort().map(function(t) {
      var active = window._investigationsFilter.tags.has(t) ? ' active' : '';
      return '<button class="card-browse-chip' + active + '"' +
             ' onclick="_toggleInvestigationChip(\'' + _esc(t) + '\', this)">' +
             _esc(t) + '</button>';
    }).join('');
    container.innerHTML = chips;
  }

  function _toggleInvestigationChip(tag, btn) {
    var s = window._investigationsFilter.tags;
    if (s.has(tag)) { s.delete(tag); btn.classList.remove('active'); }
    else { s.add(tag); btn.classList.add('active'); }
    _renderInvestigations();
  }
  window._toggleInvestigationChip = _toggleInvestigationChip;

  function _renderInvestigations() {
    var grid = document.getElementById('investigations-grid');
    if (!grid) return;
    var f = window._investigationsFilter;
    var q = f.search.toLowerCase();
    var filtered = window._investigations.filter(function(inv) {
      if (q) {
        var hay = (inv.name + ' ' + (inv.description || '') + ' ' +
                    (inv.tags || []).join(' ')).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      if (f.tags.size > 0) {
        var match = (inv.tags || []).some(function(t) { return f.tags.has(t); });
        if (!match) return false;
      }
      return true;
    });
    if (!filtered.length) {
      grid.innerHTML = '<p class="empty-state">No investigations match the filter. ' +
                       'Click <em>New investigation</em> to create one.</p>';
      grid.classList.remove('list-view');
      return;
    }
    grid.classList.toggle('list-view', window._investigationsView === 'list');
    grid.innerHTML = filtered.map(_renderInvestigationCard).join('');
  }

  function _renderInvestigationCard(inv) {
    var status = inv.status || 'planned';
    var statusClass = ({planned:'planned', running:'in_progress', ran:'complete',
                        complete:'complete', failed:'gate_pending',
                        invalid:'gate_pending'})[status] || 'planned';
    var lastRun = inv.last_run ? new Date(inv.last_run + 'Z').toLocaleString() : '—';
    return '<div class="investigation-card" onclick="_openInvestigation(\'' + _esc(inv.name) + '\')">' +
      '<div class="name">' + _esc(inv.name) + '</div>' +
      '<div class="composite"><code>' + _esc(inv.composite || '?') + '</code></div>' +
      '<div class="meta">' +
        '<span class="status-pill ' + statusClass + '">' + _esc(status) + '</span>' +
        '<span>' + (inv.n_simulations || 0) + ' sim' + ((inv.n_simulations || 0) === 1 ? '' : 's') + '</span>' +
        '<span>last run: ' + _esc(lastRun) + '</span>' +
      '</div>' +
    '</div>';
  }

  function _setInvestigationsView(view) {
    window._investigationsView = view;
    document.querySelectorAll('#investigations-toolbar .view-btn').forEach(function(b) {
      b.classList.toggle('active', b.dataset.view === view);
    });
    _renderInvestigations();
  }
  window._setInvestigationsView = _setInvestigationsView;

  // Search input live-filter
  document.addEventListener('input', function(e) {
    if (e.target && e.target.id === 'investigations-search') {
      window._investigationsFilter.search = e.target.value;
      _renderInvestigations();
    }
  });

  function _createInvestigation() {
    var srcSel = document.getElementById('create-inv-source');
    if (srcSel) srcSel.innerHTML = '<option value="">— blank composites list, add later —</option>';
    fetch('/api/composites').then(function(r) { return r.json(); }).then(function(data) {
      (data.composites || []).forEach(function(c) {
        if (srcSel) {
          var sopt = document.createElement('option');
          sopt.value = c.id;
          sopt.textContent = c.name + '  —  ' + (c.description || c.id);
          srcSel.appendChild(sopt);
        }
      });
      openModal('modal-investigation-create');
    }).catch(function() {
      openModal('modal-investigation-create');
    });
  }
  window._createInvestigation = _createInvestigation;

  function _submitInvestigationCreate(form) {
    var data = new FormData(form);
    var payload = { name: data.get('name'), composite: data.get('composite'), source: data.get('source') || '' };
    fetch('/api/investigation-create', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          var err = form.querySelector('.form-error');
          if (err) err.textContent = j.error || 'create failed';
          return;
        }
        closeModal('modal-investigation-create');
        window._investigationsLoaded = false;
        _switchPage('investigations');
      });
  }
  window._submitInvestigationCreate = _submitInvestigationCreate;

  function _openInvestigation(name) {
    window._currentInvestigation = name;
    var detail = document.getElementById('investigation-detail');
    detail.style.display = '';
    detail.innerHTML = '<p class="empty-state">Loading…</p>';
    fetch('/api/investigation/' + encodeURIComponent(name))
      .then(function(r) { return r.json(); })
      .then(function(data) { _renderInvestigationDetail(name, data); })
      .catch(function(err) {
        detail.innerHTML = '<p style="color:#c00">Failed: ' + _esc(String(err)) + '</p>';
      });
  }
  window._openInvestigation = _openInvestigation;

  function _renderInvestigationDetail(name, data) {
    var detail = document.getElementById('investigation-detail');
    if (data.error) {
      detail.innerHTML = '<p style="color:#c00">' + _esc(data.error) + '</p>';
      return;
    }
    var spec = data.spec || {};
    var vizFiles = data.viz_files || [];
    var runs = data.runs_summary || [];
    var lastRun = spec.last_run ? new Date(spec.last_run + 'Z').toLocaleString() : '—';
    var status = spec.status || 'planned';
    var statusClass = ({planned:'planned', running:'in_progress', complete:'complete',
                        failed:'gate_pending'})[status] || 'planned';

    // ── Overview-tab data (B2) ────────────────────────────────────────────────
    var ovQuestion   = (typeof spec.question === 'string') ? spec.question : '';
    var ovHypothesis = (typeof spec.hypothesis === 'string') ? spec.hypothesis : '';
    var ovStatus     = spec.status || 'draft';
    var variants     = Array.isArray(spec.variants) ? spec.variants : [];
    var baseline     = spec.baseline || '';
    var baselineEntry = null;
    for (var bi = 0; bi < variants.length; bi++) {
      if (variants[bi] && variants[bi].name === baseline) { baselineEntry = variants[bi]; break; }
    }
    var baselineSource = (baselineEntry && baselineEntry.source) ? baselineEntry.source : '—';
    var variantNames = variants.map(function(v) { return v && v.name ? v.name : ''; }).filter(Boolean);
    var comparisons  = Array.isArray(spec.comparisons) ? spec.comparisons : [];
    var comparisonNames = comparisons.map(function(c) { return c && c.name ? c.name : ''; }).filter(Boolean);
    var concText = (typeof spec.conclusions === 'string') ? spec.conclusions : '';
    var concExcerpt = concText.length > 200 ? concText.slice(0, 200) + '…' : concText;
    var statusOptions = ['draft','in-progress','completed','archived'].map(function(opt) {
      var sel = (opt === ovStatus) ? ' selected' : '';
      return '<option value="' + opt + '"' + sel + '>' + opt + '</option>';
    }).join('');
    // Per-variant run breakdown (only show if there's a meaningful breakdown)
    var runsByVariant = {};
    runs.forEach(function(r) {
      var v = (r && (r.variant || r.variant_name)) || '';
      if (v) runsByVariant[v] = (runsByVariant[v] || 0) + 1;
    });
    var breakdownKeys = Object.keys(runsByVariant);
    var runsBreakdown = '';
    if (breakdownKeys.length > 1) {
      runsBreakdown = ' <small>(' + breakdownKeys.map(function(k) {
        return _esc(k) + ': ' + runsByVariant[k];
      }).join(', ') + ')</small>';
    }
    var overviewHtml =
      '<section class="ws-overview-meta">' +
        '<label>Question' +
          '<textarea id="ov-question" rows="2">' + _esc(ovQuestion) + '</textarea>' +
        '</label>' +
        '<label>Hypothesis' +
          '<textarea id="ov-hypothesis" rows="2">' + _esc(ovHypothesis) + '</textarea>' +
        '</label>' +
        '<label>Status' +
          '<select id="ov-status">' + statusOptions + '</select>' +
        '</label>' +
      '</section>' +
      '<dl class="ws-overview-list">' +
        '<dt>Baseline</dt>' +
        '<dd>' + _esc(baseline || '—') + ' <small>(' + _esc(baselineSource) + ')</small></dd>' +
        '<dt>Variants</dt>' +
        '<dd>' + variants.length + (variantNames.length ? ' — ' + _esc(variantNames.join(', ')) : '') + '</dd>' +
        '<dt>Runs</dt>' +
        '<dd>' + runs.length + ' total' + runsBreakdown + '</dd>' +
        '<dt>Comparisons</dt>' +
        '<dd>' + comparisons.length + (comparisonNames.length ? ' — ' + _esc(comparisonNames.join(', ')) : '') + '</dd>' +
        '<dt>Visualizations</dt>' +
        '<dd>' + vizFiles.length + '</dd>' +
      '</dl>' +
      '<section class="ws-overview-conclusions">' +
        '<h3>Conclusions excerpt</h3>' +
        (concText.trim()
          ? '<p>' + _esc(concExcerpt) + '</p>'
          : '<p><em>No conclusions yet.</em></p>') +
        '<a href="#" onclick="_invDetailTab(\'conclusions\'); return false;">Read more →</a>' +
      '</section>';

    detail.innerHTML =
      '<div class="investigation-detail-header">' +
        '<div><strong style="font-size:1.1em">' + _esc(name) + '</strong> ' +
        '<span class="status-pill ' + statusClass + '" style="margin-left:8px">' + _esc(status) + '</span><br>' +
        '<small class="muted">composite: <code>' + _esc(spec.composite || '?') + '</code> · last run: ' + _esc(lastRun) + '</small></div>' +
        '<div>' +
          '<button class="action-btn" onclick="_runInvestigation(\'' + _esc(name) + '\')">' +
          (status === 'planned' ? 'Run' : 'Re-run') + '</button>' +
          '<button class="btn-mini" onclick="_deleteInvestigation(\'' + _esc(name) + '\')">Delete</button>' +
        '</div>' +
      '</div>' +
      '<div class="investigation-detail-tabs">' +
        '<button class="investigation-detail-tab active" data-tab="overview" onclick="_invDetailTab(\'overview\')">Overview</button>' +
        '<button class="investigation-detail-tab" data-tab="composites" onclick="_invDetailTab(\'composites\')">Composites</button>' +
        '<button class="investigation-detail-tab" data-tab="interventions" onclick="_invDetailTab(\'interventions\')">Interventions</button>' +
        '<button class="investigation-detail-tab" data-tab="runs" onclick="_invDetailTab(\'runs\')">Runs (' + runs.length + ')</button>' +
        '<button class="investigation-detail-tab" data-tab="viz" onclick="_invDetailTab(\'viz\')">Visualizations (' + vizFiles.length + ')</button>' +
        '<button class="investigation-detail-tab" data-tab="conclusions" onclick="_invDetailTab(\'conclusions\')">Conclusions</button>' +
      '</div>' +
      '<div class="investigation-detail-panel active" data-tab="overview">' +
        overviewHtml +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="composites">' +
        '<div style="margin-bottom:8px">' +
          '<button class="action-btn" onclick="_openAddCompositeModal()">+ Add composite</button>' +
        '</div>' +
        '<div id="inv-composites-list" style="display:grid;grid-template-columns:220px 1fr;gap:16px">' +
          '<div id="inv-composites-sidebar"></div>' +
          '<div id="inv-composite-detail" style="border-left:1px solid #eee;padding-left:14px">' +
            '<iframe id="inv-composite-explore-frame"' +
                    ' src="/loom-explore/index.html"' +
                    ' title="Composite wiring"' +
                    ' style="width:100%;height:520px;border:1px solid #ddd;background:#fff;display:none">' +
            '</iframe>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="interventions">' +
        '<div class="ws-interventions-stub">Interventions — coming in B4.</div>' +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="runs">' +
        (runs.length ? _renderInvestigationRunsTable(runs, name) : '<p class="empty-state">No runs yet — click Run to generate them.</p>') +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="viz">' +
        (vizFiles.length ?
          '<button class="btn-mini" style="margin-bottom:8px" onclick="_openAddVizModal(\'' + _esc(name) + '\')">+ Add visualization</button>' +
          vizFiles.map(function(v) {
            return '<h4 style="margin-bottom:4px">' + _esc(v.name) + '</h4>' +
                   '<iframe class="viz-frame" src="/' + _esc(v.path) + '?ts=' + Date.now() + '"></iframe>';
          }).join('') :
          '<p class="empty-state">No visualizations declared in <code>spec.yaml</code> yet. ' +
            'Click <em>Add visualization</em> to scaffold one, or edit ' +
            '<code>investigations/' + _esc(name) + '/spec.yaml</code> directly and click <em>Run</em>.</p>' +
          '<button class="action-btn" onclick="_openAddVizModal(\'' + _esc(name) + '\')">+ Add visualization</button>') +
      '</div>' +
      '<div class="investigation-detail-panel" data-tab="conclusions">' +
        '<div class="ws-conclusions-stub">Conclusions — coming in B6.</div>' +
      '</div>';

    // ── Overview-tab auto-save wiring (B2) ────────────────────────────────────
    var qEl = document.getElementById('ov-question');
    if (qEl) {
      qEl.addEventListener('blur', function() {
        _saveOverviewField(name, 'question', qEl.value);
      });
    }
    var hEl = document.getElementById('ov-hypothesis');
    if (hEl) {
      hEl.addEventListener('blur', function() {
        _saveOverviewField(name, 'hypothesis', hEl.value);
      });
    }
    var sEl = document.getElementById('ov-status');
    if (sEl) {
      sEl.value = (spec.status || 'draft');
      sEl.addEventListener('change', function() {
        _saveOverviewField(name, 'status', sEl.value);
      });
    }
  }

  function _saveOverviewField(invName, key, value) {
    var body = { investigation: invName, fields: {} };
    body.fields[key] = value;
    fetch('/api/investigation-set-overview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    })
      .then(function(r) {
        if (!r.ok) {
          return r.json().then(function(j) { alert(j.error || 'save failed'); });
        }
        if (typeof _showToast === 'function') _showToast('Saved ' + key);
      })
      .catch(function(e) { alert('Network error: ' + e); });
  }
  window._saveOverviewField = _saveOverviewField;

  function _invDetailTab(tab) {
    document.querySelectorAll('.investigation-detail-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.investigation-detail-panel').forEach(function(p) {
      p.classList.toggle('active', p.dataset.tab === tab);
    });
    if (tab === 'composites' && window._currentInvestigation) {
      _loadInvComposites(window._currentInvestigation);
    }
    if (tab === 'observables' && window._currentInvestigation) {
      _loadInvObservables(window._currentInvestigation);
    }
  }
  window._invDetailTab = _invDetailTab;

  // ── Investigation Composites tab handlers ─────────────────────────────────

  function _loadInvComposites(invName) {
    fetch('/api/investigation-composites?investigation=' + encodeURIComponent(invName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var sidebar = document.getElementById('inv-composites-sidebar');
        if (!sidebar) return;
        var entries = data.composites || [];
        if (entries.length === 0) {
          sidebar.innerHTML = '<p class="empty-state">No composites yet — click + Add composite.</p>';
          var frame = document.getElementById('inv-composite-explore-frame');
          if (frame) frame.style.display = 'none';
          return;
        }
        sidebar.innerHTML = entries.map(function(c) {
          var subtitle = c.extends
            ? '<small>extends <code>' + _esc(c.extends) + '</code></small>'
            : '<small>' + _esc(c.source || '') + '</small>';
          return '<div class="inv-composite-row" style="padding:6px;border-bottom:1px solid #eee;cursor:pointer"' +
                 ' onclick="_loadInvCompositeDetail(\'' + _esc(invName) + '\',\'' + _esc(c.name) + '\')">' +
                 '<strong>' + _esc(c.name) + '</strong><br>' + subtitle +
                 '<div style="margin-top:4px">' +
                 '<button class="btn-mini" onclick="event.stopPropagation();_openPerturbModal(\'' +
                   _esc(invName) + '\',\'' + _esc(c.name) + '\')">Perturb</button>' +
                 (c.extends
                   ? '<button class="btn-mini" onclick="event.stopPropagation();_rebuildComposite(\'' +
                     _esc(invName) + '\',\'' + _esc(c.name) + '\')">Rebuild</button>'
                   : '') +
                 '<button class="btn-mini" style="color:#c00" onclick="event.stopPropagation();_removeComposite(\'' +
                   _esc(invName) + '\',\'' + _esc(c.name) + '\')">Remove</button>' +
                 '</div></div>';
        }).join('');
        // Auto-load first composite's detail
        _loadInvCompositeDetail(invName, entries[0].name);
      });
  }
  window._loadInvComposites = _loadInvComposites;

  function _loadInvCompositeDetail(invName, compName) {
    fetch('/api/investigation-composite-doc?investigation=' + encodeURIComponent(invName) +
          '&composite=' + encodeURIComponent(compName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var iframe = document.getElementById('inv-composite-explore-frame');
        if (!iframe) return;
        if (data.error) {
          console.error('investigation-composite-doc error:', data.error);
          return;
        }
        // Show the iframe before posting so it has a layout.
        iframe.style.display = '';
        var post = function() {
          iframe.contentWindow.postMessage({
            type: 'composite:load',
            state: data.state,
            metadata: { name: compName, context: 'investigation:' + invName },
          }, '*');
        };
        if (window._loomExploreReady && window._loomExploreReady[iframe.id]) {
          post();
        } else {
          var listener = function(ev) {
            if (ev.source === iframe.contentWindow && ev.data && ev.data.type === 'explore:ready') {
              window._loomExploreReady = window._loomExploreReady || {};
              window._loomExploreReady[iframe.id] = true;
              window.removeEventListener('message', listener);
              post();
            }
          };
          window.addEventListener('message', listener);
        }
      })
      .catch(function(err) { console.error('inv composite load failed:', err); });
  }
  window._loadInvCompositeDetail = _loadInvCompositeDetail;

  // ── Investigation Observables tab handlers ────────────────────────────────

  function _loadInvObservables(invName) {
    // 1. Get composites list, 2. fetch each one's state tree, 3. union store paths,
    // 4. pre-check based on spec.observables.
    fetch('/api/investigation-composites?investigation=' + encodeURIComponent(invName))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var composites = data.composites || [];
        if (composites.length === 0) {
          var el = document.getElementById('inv-observables-tree');
          if (el) el.innerHTML = '<p class="empty-state">Add a composite first.</p>';
          return;
        }
        Promise.all(composites.map(function(c) {
          return fetch('/api/investigation-state-tree?investigation=' + encodeURIComponent(invName) +
                       '&composite=' + encodeURIComponent(c.name))
            .then(function(r) { return r.json(); })
            .then(function(tree) { return {composite: c.name, nodes: tree.nodes || []}; });
        })).then(function(trees) {
          // Union of store paths across composites
          var union = {};
          trees.forEach(function(t) {
            t.nodes.forEach(function(n) {
              if (n.kind !== 'store') return;
              var key = (n.path || []).join('.');
              if (!union[key]) {
                union[key] = {path: n.path, types: [], composites: []};
              }
              var typ = n.type || 'any';
              if (union[key].types.indexOf(typ) === -1) union[key].types.push(typ);
              if (union[key].composites.indexOf(t.composite) === -1) union[key].composites.push(t.composite);
            });
          });
          var pathKeys = Object.keys(union).sort();

          // Load current spec.yaml.observables to pre-check checkboxes
          fetch('/investigations/' + encodeURIComponent(invName) + '/spec.yaml').then(function(r) {
            return r.ok ? r.text() : '';
          }).then(function(specText) {
            var existing = [];
            var emitAll = false;
            // Naive YAML scrape — find observables: block and parse {path: [...]} entries.
            var m = specText.match(/^observables:\s*\n([\s\S]*?)(?=^[a-zA-Z_]|\s*$)/m);
            if (m) {
              var block = m[1];
              var lines = block.split(/\r?\n/);
              lines.forEach(function(line) {
                // - {path: [a, b]} OR - path: [a, b]
                var p = line.match(/path:\s*\[(.*?)\]/);
                if (p) {
                  var inner = p[1].trim();
                  if (!inner) emitAll = true;
                  else existing.push(inner.split(',').map(function(s) {
                    return s.trim().replace(/^["']|["']$/g, '');
                  }).join('.'));
                }
              });
            }

            var emitAllEl = document.getElementById('inv-emit-all');
            if (emitAllEl) emitAllEl.checked = emitAll;
            var el = document.getElementById('inv-observables-tree');
            if (!el) return;
            el.innerHTML = pathKeys.map(function(k) {
              var u = union[k];
              var checked = existing.indexOf(k) !== -1 ? ' checked' : '';
              var disabled = emitAll ? ' disabled' : '';
              return '<div style="padding:3px 0"><label>' +
                     '<input type="checkbox" data-path="' + _esc(k) + '"' + checked + disabled + '> ' +
                     '<code>' + _esc(k) + '</code> ' +
                     '<small style="color:#888"> ' + u.types.join(',') +
                     '  ·  in: ' + u.composites.join(', ') + '</small>' +
                     '</label></div>';
            }).join('');
            if (!pathKeys.length) {
              el.innerHTML = '<p class="empty-state">No store paths found in this study\'s composites.</p>';
            }
          });
        });
      });
  }
  window._loadInvObservables = _loadInvObservables;

  function _setEmitAll(on) {
    var tree = document.getElementById('inv-observables-tree');
    if (!tree) return;
    tree.querySelectorAll('input[type=checkbox][data-path]').forEach(function(cb) {
      cb.disabled = on;
    });
  }
  window._setEmitAll = _setEmitAll;

  function _saveObservables() {
    var invName = window._currentInvestigation || '';
    var emitAllEl = document.getElementById('inv-emit-all');
    var emitAll = !!(emitAllEl && emitAllEl.checked);
    var paths = [];
    if (!emitAll) {
      document.querySelectorAll('#inv-observables-tree input[type=checkbox][data-path]:checked')
        .forEach(function(cb) { paths.push(cb.dataset.path.split('.')); });
    }
    fetch('/api/investigation-set-observables', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, paths: paths, emit_all: emitAll}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var status = document.getElementById('inv-observables-status');
        if (!status) return;
        if (parts[0]) {
          status.textContent = 'Saved ' + (emitAll ? '(emit entire state)' : (paths.length + ' observable(s)'));
        } else {
          status.textContent = 'Save failed: ' + ((parts[1] || {}).error || '');
        }
      });
  }
  window._saveObservables = _saveObservables;

  function _openAddCompositeModal() {
    var sel = document.getElementById('inv-add-composite-source');
    if (!sel) return;
    sel.innerHTML = '<option value="">— pick a workspace composite —</option>';
    fetch('/api/composites').then(function(r) { return r.json(); })
      .then(function(data) {
        (data.composites || []).forEach(function(c) {
          var opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = c.name + '  —  ' + (c.description || c.id);
          sel.appendChild(opt);
        });
        openModal('modal-inv-add-composite');
      })
      .catch(function() {
        // Fallback: open modal anyway
        openModal('modal-inv-add-composite');
      });
  }
  window._openAddCompositeModal = _openAddCompositeModal;

  function _submitAddComposite(form) {
    var data = new FormData(form);
    var invName = window._currentInvestigation || '';
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var payload = {
      investigation: invName,
      name: data.get('name'),
      source: data.get('source'),
    };
    fetch('/api/investigation-composite-add', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'add failed';
          return;
        }
        closeModal('modal-inv-add-composite');
        _loadInvComposites(invName);
      });
  }
  window._submitAddComposite = _submitAddComposite;

  function _openPerturbModal(invName, parentName) {
    window._currentInvestigation = invName;
    var form = document.getElementById('form-inv-perturb');
    if (!form) return;
    form.elements['extends'].value = parentName;
    form.elements['name'].value = '';
    form.elements['parameter_overrides'].value = '';
    form.elements['process_overrides'].value = '';
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    openModal('modal-inv-perturb');
  }
  window._openPerturbModal = _openPerturbModal;

  function _submitPerturb(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var parseOpt = function(raw, fieldName) {
      raw = (raw || '').trim();
      if (!raw) return null;
      try { return JSON.parse(raw); }
      catch (e) {
        if (errEl) errEl.textContent = 'Invalid JSON in ' + fieldName + ': ' + String(e);
        return undefined;
      }
    };
    var po = parseOpt(data.get('parameter_overrides'), 'parameter_overrides');
    if (po === undefined) return;
    var procO = parseOpt(data.get('process_overrides'), 'process_overrides');
    if (procO === undefined) return;
    var payload = {
      investigation: window._currentInvestigation || '',
      name: data.get('name'),
      extends: data.get('extends'),
    };
    if (po) payload.parameter_overrides = po;
    if (procO) payload.process_overrides = procO;
    fetch('/api/investigation-composite-perturb', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'perturb failed';
          return;
        }
        closeModal('modal-inv-perturb');
        _loadInvComposites(payload.investigation);
      });
  }
  window._submitPerturb = _submitPerturb;

  function _rebuildComposite(invName, compName) {
    fetch('/api/investigation-composite-rebuild', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, name: compName}),
    }).then(function() {
      _loadInvComposites(invName);
      _loadInvCompositeDetail(invName, compName);
    });
  }
  window._rebuildComposite = _rebuildComposite;

  function _removeComposite(invName, compName) {
    if (!confirm('Remove composite ' + compName + '?')) return;
    fetch('/api/investigation-composite', {
      method: 'DELETE', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: invName, name: compName}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (j.dependents) {
            alert('Cannot remove — has dependents:\n - ' + j.dependents.join('\n - '));
          } else {
            alert(j.error || 'remove failed');
          }
          return;
        }
        _loadInvComposites(invName);
      });
  }
  window._removeComposite = _removeComposite;

  // ── End Investigation Composites tab handlers ─────────────────────────────

  function _renderInvestigationRunsTable(runs, investigationName) {
    var rows = runs.map(function(r) {
      var pstr = Object.keys(r.params || {}).map(function(k) {
        return k + '=' + r.params[k];
      }).join(', ') || '—';
      var statusClass = ({completed: 'completed', failed: 'failed',
                          running: 'running'})[r.status] || 'planned';
      var rowId = _esc(r.run_id);
      var paramsJson = _esc(JSON.stringify(r.params || {}));
      return '<tr><td>' + _esc(r.sim_name) + '</td>' +
             '<td><code>' + _esc(pstr) + '</code></td>' +
             '<td>' + (r.n_steps || 0) + '</td>' +
             '<td><span class="ce-history-status ' + statusClass + '">' + _esc(r.status) + '</span></td>' +
             '<td><code style="font-size:0.78em">' + rowId.slice(-12) + '</code></td>' +
             '<td><button class="btn-mini" onclick=\'_dupRun("' + _esc(investigationName) + '","' + rowId + '","' + _esc(r.sim_name) + '",' + paramsJson + ',' + (r.n_steps || 10) + ')\'>Duplicate</button> ' +
                  '<button class="btn-mini" style="color:#c00" onclick="_deleteRun(\'' + _esc(investigationName) + '\',\'' + rowId + '\')">Delete</button></td>' +
           '</tr>';
    }).join('');
    var clearBtn = '<div style="margin-bottom:6px"><button class="btn-mini" style="color:#c00" ' +
                   'onclick="_clearRuns(\'' + _esc(investigationName) + '\')">Clear all runs</button></div>';
    return clearBtn + '<table style="width:100%"><thead><tr>' +
      '<th>Simulation</th><th>Params</th><th>Steps</th><th>Status</th><th>Run id</th><th>Actions</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function _runInvestigation(name) {
    var detail = document.getElementById('investigation-detail');
    var btn = detail.querySelector('button.action-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    fetch('/api/investigation-run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) { alert('Run failed: ' + (j.error || 'unknown')); }
        // Refresh both the list (status update) and the detail panel
        window._investigationsLoaded = false;
        _loadInvestigations();
        _openInvestigation(name);
      })
      .catch(function(err) { alert('Network error: ' + err); });
  }
  window._runInvestigation = _runInvestigation;

  function _deleteInvestigation(name) {
    if (!confirm('Delete investigation "' + name + '"? This removes its runs.db, visualizations, and spec.yaml.')) return;
    fetch('/api/investigation-delete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (!j.ok) { alert('Delete failed: ' + (j.error || 'unknown')); return; }
      var detail = document.getElementById('investigation-detail');
      if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
      window._investigationsLoaded = false;
      _loadInvestigations();
    });
  }
  window._deleteInvestigation = _deleteInvestigation;

  function _deleteRun(investigationName, runId) {
    if (!confirm('Delete run ' + runId.slice(-12) + '?')) return;
    fetch('/api/investigation-run-delete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: investigationName, run_id: runId}),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (!j.ok) { alert('Delete failed: ' + (j.error || 'unknown')); return; }
      _openInvestigation(investigationName);
    });
  }
  window._deleteRun = _deleteRun;

  function _clearRuns(investigationName) {
    if (!confirm('Clear ALL runs from ' + investigationName + '? (visualizations will be empty until you re-run)')) return;
    fetch('/api/investigation-runs-clear', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({investigation: investigationName}),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (!j.ok) { alert('Clear failed: ' + (j.error || 'unknown')); return; }
      _openInvestigation(investigationName);
    });
  }
  window._clearRuns = _clearRuns;

  function _dupRun(investigationName, runId, simName, params, steps) {
    // Prompt the user to edit params as JSON, then submit.
    var current = JSON.stringify(params, null, 2);
    var edited = prompt('Edit overrides for the duplicated run:\n(JSON; will append as a new ad-hoc run)', current);
    if (edited === null) return;
    var overrides;
    try { overrides = JSON.parse(edited); }
    catch (e) { alert('Invalid JSON: ' + e); return; }
    fetch('/api/investigation-run-one', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        investigation: investigationName,
        sim_name: simName + '-copy',
        overrides: overrides,
        steps: steps,
      }),
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (!j.ok) { alert('Duplicate-run failed: ' + (j.error || 'unknown')); return; }
      _openInvestigation(investigationName);
    });
  }
  window._dupRun = _dupRun;

  function _openWorkspaceVizModal() {
    var classSel = document.getElementById('viz-class-picker');
    var alreadyEl = document.getElementById('viz-already-registered');
    if (classSel) classSel.innerHTML = '<option value="">— none (description-only) —</option>';
    if (alreadyEl) alreadyEl.textContent = '';
    Promise.all([
      fetch('/api/visualization-classes').then(function(r) { return r.json(); }),
      fetch('/api/visualization-instances').then(function(r) { return r.json(); }),
      fetch('/workspace.yaml').then(function(r) { return r.ok ? r.text() : ''; }),
    ]).then(function(parts) {
      var classes = (parts[0] && parts[0].classes) || [];
      var instances = (parts[1] && parts[1].instances) || [];
      if (classSel) {
        classes.forEach(function(c) {
          var opt = document.createElement('option');
          opt.value = c.name;
          opt.textContent = c.name + (c.doc ? '  —  ' + c.doc : '');
          classSel.appendChild(opt);
        });
      }
      // Surface the existing workspace.yaml viz entries by name so the user
      // doesn't collide with one they already added.
      var ws = parts[2] || '';
      var existing = [];
      var inViz = false;
      ws.split(/\r?\n/).forEach(function(line) {
        if (/^visualizations:/.test(line)) { inViz = true; return; }
        if (inViz && /^[A-Za-z_]/.test(line)) { inViz = false; return; }
        if (inViz) {
          var m = line.match(/^\s*-\s*name:\s*(\S+)/);
          if (m) existing.push(m[1]);
        }
      });
      if (alreadyEl) {
        if (existing.length) {
          var instMap = {};
          instances.forEach(function(i) { instMap[i.name] = i['class']; });
          alreadyEl.innerHTML = 'Already registered: ' + existing.map(function(n) {
            return instMap[n]
              ? '<code>' + n + '</code> (' + instMap[n] + ')'
              : '<code>' + n + '</code>';
          }).join(', ');
        } else {
          alreadyEl.textContent = 'No visualizations registered yet.';
        }
      }
      openModal('modal-visualization');
    });
  }
  window._openWorkspaceVizModal = _openWorkspaceVizModal;

  function _openAddVizModal(investigationName) {
    document.getElementById('add-viz-investigation').value = investigationName;
    var sel = document.getElementById('add-viz-class');
    var cfgField = document.querySelector('#form-investigation-add-viz textarea[name="config"]');
    sel.innerHTML = '<option value="">— pick a registered instance or raw class —</option>';
    // Stash instance configs on the select so onchange can auto-fill.
    sel._vizInstanceConfigs = {};
    Promise.all([
      fetch('/api/visualization-instances').then(function(r) { return r.json(); }),
      fetch('/api/visualization-classes').then(function(r) { return r.json(); }),
    ]).then(function(parts) {
      var instances = (parts[0] && parts[0].instances) || [];
      var classes = (parts[1] && parts[1].classes) || [];
      if (instances.length) {
        var gi = document.createElement('optgroup');
        gi.label = 'Registered instances (config pre-filled)';
        instances.forEach(function(inst) {
          var opt = document.createElement('option');
          opt.value = inst.address;
          opt.textContent = inst.name + '  —  ' + inst['class'] + (inst.description ? ' · ' + inst.description : '');
          opt.dataset.instanceName = inst.name;
          sel._vizInstanceConfigs[opt.value + '|' + inst.name] = inst.config || {};
          gi.appendChild(opt);
        });
        sel.appendChild(gi);
      }
      if (classes.length) {
        var gc = document.createElement('optgroup');
        gc.label = 'Raw classes (write config JSON)';
        classes.forEach(function(c) {
          var opt = document.createElement('option');
          opt.value = c.address;
          opt.textContent = c.name + (c.doc ? '  —  ' + c.doc : '');
          gc.appendChild(opt);
        });
        sel.appendChild(gc);
      }
      sel.onchange = function() {
        var picked = sel.options[sel.selectedIndex];
        if (!picked) return;
        var instName = picked.dataset && picked.dataset.instanceName;
        if (instName) {
          var key = sel.value + '|' + instName;
          var cfg = sel._vizInstanceConfigs[key] || {};
          if (cfgField) cfgField.value = JSON.stringify(cfg, null, 2);
          // Default the new investigation viz name to the instance name when empty.
          var nameField = document.querySelector('#form-investigation-add-viz input[name="name"]');
          if (nameField && !nameField.value) nameField.value = instName;
        }
      };
      openModal('modal-investigation-add-viz');
    });
  }
  window._openAddVizModal = _openAddVizModal;

  function _submitAddViz(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    if (errEl) errEl.textContent = '';
    var configRaw = (data.get('config') || '').trim();
    var config = {};
    if (configRaw) {
      try { config = JSON.parse(configRaw); }
      catch (e) {
        if (errEl) errEl.textContent = 'Invalid JSON in config: ' + String(e);
        return;
      }
    }
    var payload = {
      investigation: data.get('investigation'),
      name: data.get('name'),
      address: data.get('address'),
      config: config,
    };
    fetch('/api/investigation-add-viz', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'add failed';
          return;
        }
        closeModal('modal-investigation-add-viz');
        fetch('/api/investigation-render-viz', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: payload.investigation}),
        }).then(function() {
          _openInvestigation(payload.investigation);  // refresh detail panel
        });
      });
  }
  window._submitAddViz = _submitAddViz;

  // ---------------------------------------------------------------------------
  // Viz generate / accept / migration (Task 8)
  // ---------------------------------------------------------------------------

  function _submitVizGenerate(form) {
    var data = new FormData(form);
    var errEl = form.querySelector('.form-error');
    var statusEl = document.getElementById('viz-generate-status');
    if (errEl) errEl.textContent = '';
    var payload = {
      name: data.get('name'),
      description: data.get('description'),
    };
    fetch('/api/visualization-generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        if (!ok) {
          if (errEl) errEl.textContent = j.error || 'generate failed';
          return;
        }
        if (statusEl) statusEl.innerHTML =
          'Request written to <code>' + j.request_path + '</code>.<br>' +
          'In your active Claude Code session, run <code>' + j.skill_command + '</code>.<br>' +
          'Target file: <code>' + j.target_file + '</code>.<br>' +
          'Polling for completion…';
        _pollForGeneratedClass(payload.name, j.target_file, 0);
      });
  }
  window._submitVizGenerate = _submitVizGenerate;

  function _pollForGeneratedClass(name, targetFile, attempt) {
    if (attempt > 600) {  // ~5 min
      var statusEl = document.getElementById('viz-generate-status');
      if (statusEl) statusEl.innerHTML += '<br><span style="color:#991b1b">Timed out waiting.</span>';
      return;
    }
    fetch('/' + targetFile + '?_=' + Date.now()).then(function(r) {
      if (r.ok) {
        var statusEl = document.getElementById('viz-generate-status');
        if (statusEl) statusEl.innerHTML +=
          '<br><span style="color:#1f7a3a">File detected.</span> ' +
          '<button class="btn-mini" onclick="_vizClassPreview(\'local:' + name + '\',\'' + name + '\')">' +
          'Preview</button> ' +
          '<button class="btn-mini" onclick="_acceptGeneratedClass(\'' + name + '\')">Accept &amp; commit</button>';
      } else {
        setTimeout(function() { _pollForGeneratedClass(name, targetFile, attempt + 1); }, 500);
      }
    }).catch(function() {
      setTimeout(function() { _pollForGeneratedClass(name, targetFile, attempt + 1); }, 500);
    });
  }

  function _acceptGeneratedClass(name) {
    fetch('/api/visualization-accept', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name}),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
      .then(function(parts) {
        var ok = parts[0], j = parts[1];
        var statusEl = document.getElementById('viz-generate-status');
        if (!ok) {
          if (statusEl) statusEl.innerHTML +=
            '<br><span style="color:#991b1b">Accept failed: ' + (j.error || '') + '</span>';
          return;
        }
        if (statusEl) statusEl.innerHTML +=
          '<br><span style="color:#1f7a3a">Committed. Reloading catalog…</span>';
        setTimeout(function() { window.location.reload(); }, 600);
      });
  }
  window._acceptGeneratedClass = _acceptGeneratedClass;

})();
