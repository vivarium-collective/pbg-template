// walkthrough.js — v0.5.2: composite explorer UX fixes (no focus-mode hijack, one-row-per-param layout, lazy-load composite cache); v0.5.1: composite explorer page (bigraph-viz + test run + promote to simulation); v0.4.14: Available Composites picker + Emitter Use feedback + drop process multi-select; v0.4.5: _renderInstallError structured diagnosis; v0.4.1: _loadCatalog + _installFromCatalog; v0.4.0b: active-branch workstream strip; v0.3.7-A: _installImport; v0.3.6: Registry tab; v0.1.9: drag-drop uploads; v0.1.7: interactive forms.
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
  }

  function _initMenuNav() {
    // Focus mode: ?focus=<panel> hides everything except the named panel.
    var params = new URLSearchParams(window.location.search);
    var focus = params.get('focus');
    if (focus) {
      var validPages = ['workspace-inputs', 'simulation-setup', 'visualizations', 'registry', 'build-model', 'branches', 'composite-explore'];
      if (validPages.indexOf(focus) >= 0) {
        document.body.classList.add('focus-mode', 'focus-' + focus);
        _switchPage(focus);
        return; // skip normal hash-based routing
      }
    }

    function fromHash() {
      var h = (window.location.hash || '').replace(/^#/, '');
      // phase anchors (#phase-N) auto-route to build-model page
      if (/^phase-\d+$/.test(h)) {
        _switchPage('build-model');
        // let the browser scroll to the anchor naturally
        return;
      }
      var validPages = ['workspace-inputs', 'registry', 'simulation-setup', 'visualizations', 'build-model', 'branches', 'composite-explore'];
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
      return '<div class="picker-row">' +
        '<div class="picker-row-main">' +
          '<strong>' + _esc(it.name) + '</strong>' +
          ' <code class="muted" style="font-size:0.82em">' + _esc(it.address) + '</code>' +
          schemaSnippet +
        '</div>' +
        '<div class="picker-row-actions">' +
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
      // Open Add visualization modal with a class-reference description.
      openModal('modal-visualization');
      var modal = document.getElementById('modal-visualization');
      if (modal) {
        var nameInput = modal.querySelector('input[name=viz_name]');
        var descTa = modal.querySelector('textarea[name=description]');
        if (nameInput) nameInput.value = name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
        if (descTa) descTa.value = 'Use the registered ' + name + ' class from the Registry. ' +
          'Run-time instantiation of ' + name + ' against the gathered emitter results.';
      }
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
  // Composites browser (v0.4.14)
  // -------------------------------------------------------------------------

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
          return '<div class="module-card">' +
            '<div class="module-card-header"><strong>' + _esc(c.name) + '</strong></div>' +
            '<p class="module-desc">' + _esc(c.description || '(no description)') + '</p>' +
            requires +
            paramSummary +
            '<div class="module-action">' +
              '<button class="action-btn" onclick="_openCompositeExplorer(\'' + _esc(c.id) + '\')">Use</button>' +
            '</div>' +
          '</div>';
        });
        container.innerHTML = cards.join('');
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
  // Catalog browser (v0.4.1)
  // -------------------------------------------------------------------------

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
        var cards = data.modules.map(function(m) {
          var actionBtn = m.installed
            ? '<span class="status-pill installed">installed</span>'
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

  function _vizPreview(name) {
    alert(
      'Preview not yet implemented (planned v0.4.3). For now, open\n' +
      '.pbg/viz-responses/' + name + '.py\n' +
      'and run: python3 .pbg/viz-responses/' + name + '.py | head'
    );
  }
  window._vizPreview = _vizPreview;

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
        // Render diagram
        document.getElementById('ce-diagram').innerHTML = data.svg || '<em>(no diagram)</em>';
        // Render parameter editor
        _ceRenderParameters(data.parameters);
        // Render state JSON
        document.getElementById('ce-state-json').textContent =
          JSON.stringify(data.state, null, 2);
      })
      .catch(function(err) {
        document.getElementById('ce-loading').innerHTML =
          '<span style="color:#c00">Network error: ' + _esc(String(err)) + '</span>';
      });
  }

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

})();
