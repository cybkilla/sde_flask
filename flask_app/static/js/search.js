// search.js — Autocomplete ticker search
// J1  : stub (ne fait rien, évite les erreurs 404)
// J4  : implémentation AJAX complète vers /api/search

(function () {
  const input    = document.getElementById("sde-search-input");
  const dropdown = document.getElementById("sde-search-dropdown");
  const btn      = document.getElementById("sde-analyze-btn");

  if (!input) return; // page sans sidebar (ex: login)

  let selectedTicker = null;
  let debounceTimer  = null;

  // ── Sélection d'un ticker ────────────────────────────────────────────────────
  function selectTicker(ticker, label) {
    selectedTicker   = ticker;
    input.value      = label;
    btn.disabled     = false;
    dropdown.innerHTML = "";
    dropdown.classList.add("d-none");
  }

  // ── Bouton Analyser ──────────────────────────────────────────────────────────
  btn.addEventListener("click", function () {
    if (selectedTicker) {
      window.location.href = "/analyze/" + encodeURIComponent(selectedTicker);
    }
  });

  // ── Saisie → appel AJAX /api/search (J4) ────────────────────────────────────
  input.addEventListener("input", function () {
    const q = this.value.trim();
    btn.disabled   = true;
    selectedTicker = null;

    clearTimeout(debounceTimer);

    if (q.length < 2) {
      dropdown.classList.add("d-none");
      return;
    }

    debounceTimer = setTimeout(function () {
      fetch("/api/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          renderDropdown(data);
        })
        .catch(function () {
          dropdown.classList.add("d-none");
        });
    }, 280); // debounce 280 ms
  });

  // ── Rendu dropdown ───────────────────────────────────────────────────────────
  function renderDropdown(items) {
    dropdown.innerHTML = "";

    if (!items || items.length === 0) {
      dropdown.classList.add("d-none");
      return;
    }

    items.slice(0, 8).forEach(function (item) {
      const ticker = item.ticker || item.symbol || "";
      const name   = item.shortName || item.longName || ticker;
      const li     = document.createElement("li");
      li.className = "list-group-item list-group-item-action d-flex justify-content-between";
      li.innerHTML =
        '<span>' + escHtml(name) + '</span>' +
        '<span class="text-muted small">' + escHtml(ticker) + '</span>';
      li.addEventListener("click", function () {
        selectTicker(ticker, name + " (" + ticker + ")");
      });
      dropdown.appendChild(li);
    });

    dropdown.classList.remove("d-none");
  }

  // ── Fermer dropdown si clic ailleurs ────────────────────────────────────────
  document.addEventListener("click", function (e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.add("d-none");
    }
  });

  // ── Escape HTML ─────────────────────────────────────────────────────────────
  function escHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

})();
