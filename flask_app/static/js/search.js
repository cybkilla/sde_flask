// search.js — Autocomplete ticker + gestion sidebar
// J2  : badge ticker, bouton effacer, saisie directe fallback
// J4  : AJAX /api/search (debounce déjà en place)

(function () {
  const input       = document.getElementById("sde-search-input");
  const dropdown    = document.getElementById("sde-search-dropdown");
  const btn         = document.getElementById("sde-analyze-btn");
  const badge       = document.getElementById("sde-ticker-badge");
  const badgeLabel  = document.getElementById("sde-ticker-label");
  const clearBtn    = document.getElementById("sde-ticker-clear");
  const directWrap  = document.getElementById("sde-direct-input-wrapper");
  const directInput = document.getElementById("sde-direct-input");

  if (!input) return;

  let selectedTicker = null;
  let debounceTimer  = null;

  // ── Sélectionne un ticker (depuis dropdown) ───────────────────────────────
  function selectTicker(ticker, name) {
    selectedTicker = ticker.toUpperCase();
    input.value    = name + " (" + selectedTicker + ")";
    closeDropdown();
    showBadge(selectedTicker);
    btn.disabled = false;
    if (directWrap) directWrap.classList.add("d-none");
  }

  function showBadge(ticker) {
    if (!badge || !badgeLabel) return;
    badgeLabel.textContent = ticker;
    badge.classList.remove("d-none");
  }

  function clearSelection() {
    selectedTicker = null;
    input.value    = "";
    btn.disabled   = true;
    if (badge)      badge.classList.add("d-none");
    if (directWrap) directWrap.classList.add("d-none");
    closeDropdown();
    input.focus();
  }

  if (clearBtn) clearBtn.addEventListener("click", clearSelection);

  // ── Bouton Analyser ───────────────────────────────────────────────────────
  btn.addEventListener("click", function () {
    const ticker = selectedTicker
      || (directInput && directInput.value.trim().toUpperCase());
    if (!ticker) return;
    showLoadingOverlay(ticker);
    window.location.href = "/analyze/" + encodeURIComponent(ticker);
  });

  function showLoadingOverlay(ticker) {
    const div = document.createElement("div");
    div.id = "sde-page-loading";
    div.innerHTML =
      '<div style="position:fixed;inset:0;background:rgba(255,255,255,.88);' +
      'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
      'z-index:9999;gap:16px">' +
      '<div class="spinner-border text-success" style="width:2.5rem;height:2.5rem" role="status">' +
      '<span class="visually-hidden">Chargement…</span></div>' +
      '<div style="font-size:.95rem;color:#374151;font-weight:500">' +
      'Analyse de <strong>' + ticker + '</strong> en cours…</div>' +
      '<div style="font-size:.75rem;color:#9ca3af">Données marché · actualités · IA</div>' +
      '</div>';
    document.body.appendChild(div);
  }

  // ── Saisie recherche → AJAX ───────────────────────────────────────────────
  input.addEventListener("input", function () {
    const q = this.value.trim();
    selectedTicker = null;
    btn.disabled   = true;
    if (badge) badge.classList.add("d-none");
    clearTimeout(debounceTimer);

    if (q.length < 2) {
      closeDropdown();
      if (directWrap) directWrap.classList.add("d-none");
      return;
    }

    debounceTimer = setTimeout(function () {
      fetch("/api/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || data.error || data.length === 0) {
            closeDropdown();
            // Fallback saisie directe si ça ressemble à un ticker (≤ 6 chars, sans espace)
            if (directWrap && q.length <= 6 && !q.includes(" ")) {
              directInput.value = q.toUpperCase();
              directWrap.classList.remove("d-none");
              selectedTicker = q.toUpperCase();
              btn.disabled   = false;
            }
          } else {
            if (directWrap) directWrap.classList.add("d-none");
            renderDropdown(data);
          }
        })
        .catch(function () { closeDropdown(); });
    }, 280);
  });

  // ── Saisie directe ticker ─────────────────────────────────────────────────
  if (directInput) {
    directInput.addEventListener("input", function () {
      const v    = this.value.trim().toUpperCase();
      this.value = v;
      selectedTicker = v || null;
      btn.disabled   = !v;
      if (v) showBadge(v); else if (badge) badge.classList.add("d-none");
    });
  }

  // ── Rendu dropdown ────────────────────────────────────────────────────────
  function renderDropdown(items) {
    dropdown.innerHTML = "";
    items.slice(0, 8).forEach(function (item) {
      const ticker   = (item.ticker || item.symbol || "").toUpperCase();
      const name     = item.shortName || item.longName || ticker;
      const exchange = item.exchange ? " · " + item.exchange : "";
      const li       = document.createElement("li");
      li.className   = "list-group-item list-group-item-action d-flex justify-content-between align-items-center";
      li.innerHTML =
        '<span class="text-truncate me-2">' + escHtml(name) + '</span>' +
        '<span class="text-muted small flex-shrink-0 text-end">' +
          escHtml(ticker) +
          '<span style="font-size:.7rem;opacity:.6">' + escHtml(exchange) + '</span>' +
        '</span>';
      li.addEventListener("click", function () { selectTicker(ticker, name); });
      dropdown.appendChild(li);
    });
    dropdown.classList.remove("d-none");
  }

  function closeDropdown() {
    dropdown.innerHTML = "";
    dropdown.classList.add("d-none");
  }

  document.addEventListener("click", function (e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) closeDropdown();
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") clearSelection();
  });

  function escHtml(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

})();
