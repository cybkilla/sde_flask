// search.js — Autocomplete ticker (navbar + hero home search)

(function () {
  "use strict";

  let selectedTicker = null;
  let debounceTimer  = null;

  // ── Shared navigate / overlay ─────────────────────────────────────────────
  function navigateTo(ticker) {
    showLoadingOverlay(ticker);
    window.location.href = "/analyze/" + encodeURIComponent(ticker);
  }

  var _STEPS = [
    "Récupération des données marché…",
    "Calcul des indicateurs · RSI · MACD · Bollinger…",
    "Collecte des actualités & presse financière…",
    "Analyse des transactions dirigeants…",
    "Scoring · technique · fondamental · médiatique…",
    "Analyse IA · génération de la recommandation…",
  ];
  // Délai (ms) avant de passer à l'étape suivante
  var _STEP_DELAYS = [2200, 2200, 2500, 2500, 3000];

  function _cycleSteps(el) {
    var i = 1;
    function next() {
      if (i >= _STEPS.length || !document.getElementById("sde-page-loading")) return;
      el.style.opacity = "0";
      setTimeout(function () {
        el.textContent  = _STEPS[i];
        el.style.opacity = "1";
        i++;
        if (i < _STEPS.length) setTimeout(next, _STEP_DELAYS[i - 1] || 2500);
      }, 350);
    }
    setTimeout(next, _STEP_DELAYS[0]);
  }

  function showLoadingOverlay(label) {
    document.body.classList.add("sde-loading");
    const existing = document.getElementById("sde-page-loading");
    if (existing) return;
    const div = document.createElement("div");
    div.id = "sde-page-loading";
    div.innerHTML =
      '<div class="spinner-border" style="width:2.5rem;height:2.5rem;color:var(--sde-teal)" role="status">' +
      '<span class="visually-hidden">Chargement…</span></div>' +
      '<div style="font-size:.95rem;font-weight:500;color:var(--sde-text)">' +
      escHtml(label) + '</div>' +
      '<div id="sde-step-label" style="font-size:.75rem;color:var(--sde-muted);transition:opacity .35s ease">' +
      _STEPS[0] + '</div>';
    document.body.appendChild(div);
    _cycleSteps(document.getElementById("sde-step-label"));
  }

  // Exposé globalement pour watchlist.js et les liens "Actualiser"
  window.sdeShowOverlay = showLoadingOverlay;

  // Nettoie l'overlay si le navigateur restaure la page depuis le bfcache
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) {
      var overlay = document.getElementById("sde-page-loading");
      if (overlay) overlay.remove();
      document.body.classList.remove("sde-loading");
    }
  });

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── AJAX search ───────────────────────────────────────────────────────────
  function fetchTickers(q, cb) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      fetch("/api/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(cb)
        .catch(function () { cb([]); });
    }, 280);
  }

  // ── Dropdown renderer (shared) ────────────────────────────────────────────
  function renderDropdown(drop, items, onPick) {
    drop.innerHTML = "";
    items.slice(0, 8).forEach(function (item) {
      const ticker   = (item.ticker || item.symbol || "").toUpperCase();
      const name     = item.shortName || item.longName || ticker;
      const exchange = item.exchange ? " · " + item.exchange : "";
      const li       = document.createElement("li");
      li.className   = "sde-drop-item";
      li.innerHTML   =
        '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
        escHtml(name) + '</span>' +
        '<span style="font-size:.78rem;color:var(--sde-muted);flex-shrink:0">' +
        escHtml(ticker) +
        '<span style="font-size:.68rem;opacity:.7">' + escHtml(exchange) + '</span></span>';
      li.addEventListener("mousedown", function (e) {
        e.preventDefault();
        drop.classList.add("d-none");
        onPick(ticker, name);
      });
      drop.appendChild(li);
    });
    drop.classList.remove("d-none");
  }

  function closeDropdown(drop) {
    drop.innerHTML = "";
    drop.classList.add("d-none");
  }

  // ══ NAVBAR SEARCH ════════════════════════════════════════════════════════
  (function initNavSearch() {
    const input      = document.getElementById("sde-search-input");
    const drop       = document.getElementById("sde-search-dropdown");
    const btn        = document.getElementById("sde-analyze-btn");
    const badge      = document.getElementById("sde-ticker-badge");
    const badgeLabel = document.getElementById("sde-ticker-label");
    const clearBtn   = document.getElementById("sde-ticker-clear");
    const directWrap = document.getElementById("sde-direct-input-wrapper");
    const directIn   = document.getElementById("sde-direct-input");

    if (!input || !drop || !btn) return;

    function selectTicker(ticker, name) {
      selectedTicker = ticker.toUpperCase();
      input.value    = name + " (" + selectedTicker + ")";
      closeDropdown(drop);
      if (badgeLabel) badgeLabel.textContent = selectedTicker;
      if (badge)      badge.classList.remove("d-none");
      btn.disabled   = false;
      if (directWrap) directWrap.classList.add("d-none");
    }

    function clearSelection() {
      selectedTicker = null;
      input.value    = "";
      btn.disabled   = true;
      if (badge)      badge.classList.add("d-none");
      if (directWrap) directWrap.classList.add("d-none");
      closeDropdown(drop);
      input.focus();
    }

    if (clearBtn) clearBtn.addEventListener("click", clearSelection);

    btn.addEventListener("click", function () {
      const t = selectedTicker
        || (directIn && directIn.value.trim().toUpperCase());
      if (!t) return;
      navigateTo(t);
    });

    input.addEventListener("input", function () {
      const q = this.value.trim();
      selectedTicker = null;
      btn.disabled   = true;
      if (badge) badge.classList.add("d-none");

      if (q.length < 2) {
        closeDropdown(drop);
        if (directWrap) directWrap.classList.add("d-none");
        return;
      }

      fetchTickers(q, function (data) {
        if (!data || data.error || data.length === 0) {
          closeDropdown(drop);
          if (directWrap && q.length <= 6 && !q.includes(" ")) {
            if (directIn) directIn.value = q.toUpperCase();
            directWrap.classList.remove("d-none");
            selectedTicker = q.toUpperCase();
            btn.disabled   = false;
          }
        } else {
          if (directWrap) directWrap.classList.add("d-none");
          renderDropdown(drop, data, selectTicker);
        }
      });
    });

    if (directIn) {
      directIn.addEventListener("input", function () {
        const v = this.value.trim().toUpperCase();
        this.value = v;
        selectedTicker = v || null;
        btn.disabled   = !v;
        if (v && badgeLabel) {
          badgeLabel.textContent = v;
          if (badge) badge.classList.remove("d-none");
        } else if (badge) {
          badge.classList.add("d-none");
        }
      });
    }

    document.addEventListener("click", function (e) {
      if (!input.contains(e.target) && !drop.contains(e.target)) closeDropdown(drop);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") clearSelection();
    });
  })();

  // ══ HOME HERO SEARCH ══════════════════════════════════════════════════════
  (function initHeroSearch() {
    const input = document.getElementById("sde-hero-input");
    const drop  = document.getElementById("sde-hero-drop");
    if (!input || !drop) return;

    input.addEventListener("input", function () {
      const q = this.value.trim();
      if (q.length < 2) { closeDropdown(drop); return; }
      fetchTickers(q, function (data) {
        if (!data || data.error || data.length === 0) {
          // Direct ticker fallback: allow short strings like "AAPL"
          if (q.length <= 6 && !q.includes(" ")) {
            const li = document.createElement("li");
            li.className = "sde-drop-item";
            li.innerHTML =
              '<span style="color:var(--sde-muted);font-size:.83rem">Analyser le ticker</span>' +
              '<span style="font-weight:600;color:var(--sde-navy)">' + escHtml(q.toUpperCase()) + '</span>';
            li.addEventListener("mousedown", function (e) {
              e.preventDefault();
              drop.classList.add("d-none");
              navigateTo(q.toUpperCase());
            });
            drop.innerHTML = "";
            drop.appendChild(li);
            drop.classList.remove("d-none");
          } else {
            closeDropdown(drop);
          }
        } else {
          renderDropdown(drop, data, function (ticker) { navigateTo(ticker); });
        }
      });
    });

    document.addEventListener("click", function (e) {
      if (!input.contains(e.target) && !drop.contains(e.target)) closeDropdown(drop);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { input.value = ""; closeDropdown(drop); }
    });
  })();

})();
