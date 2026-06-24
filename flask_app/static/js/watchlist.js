// watchlist.js — gestion AJAX watchlist (modal)

(function () {
  "use strict";

  const CSRF = (function () {
    const t = document.querySelector('meta[name="csrf-token"]');
    return t ? t.content : "";
  })();

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Rendu modal ───────────────────────────────────────────────────────────
  function renderWatchlist(items) {
    const container = document.getElementById("sde-watchlist");
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML =
        '<p class="text-center py-3" style="font-size:.8rem;color:var(--sde-muted)">' +
        'Aucune valeur suivie.</p>';
      return;
    }

    const ul = document.createElement("ul");
    ul.className = "list-unstyled mb-0";

    items.forEach(function (item) {
      const ticker  = (item.ticker || "").toUpperCase();
      const company = item.company || ticker;
      const li      = document.createElement("li");
      li.className  = "sde-wl-item";
      li.dataset.ticker = ticker;
      const a = document.createElement("a");
      a.href  = "/analyze/" + encodeURIComponent(ticker);
      a.style.cssText = "font-weight:600;color:var(--sde-navy);flex-shrink:0;text-decoration:none";
      a.textContent   = ticker;
      a.addEventListener("click", function (e) {
        e.preventDefault();
        if (window.sdeShowOverlay) window.sdeShowOverlay("Analyse de " + ticker + "…");
        else document.body.classList.add("sde-loading");
        window.location.href = this.href;
      });

      const co  = document.createElement("span");
      co.className = "co";
      co.title     = company;
      co.textContent = (company && company !== ticker) ? company : "";

      const rm  = document.createElement("button");
      rm.className      = "sde-wl-rm";
      rm.dataset.ticker = ticker;
      rm.title          = "Retirer";
      rm.textContent    = "✕";

      li.appendChild(a);
      li.appendChild(co);
      li.appendChild(rm);
      ul.appendChild(li);
    });

    container.innerHTML = "";
    container.appendChild(ul);

    container.querySelectorAll(".sde-wl-rm").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        const t = this.dataset.ticker;
        postJSON("/watchlist/remove", { ticker: t }).then(function (data) {
          if (data.ok) {
            const li = container.querySelector('li[data-ticker="' + t + '"]');
            if (li) li.remove();
            if (!container.querySelector("li")) {
              container.innerHTML =
                '<p class="text-center py-3" style="font-size:.8rem;color:var(--sde-muted)">Aucune valeur suivie.</p>';
            }
            syncPageButton(t, false);
          }
        });
      });
    });
  }

  // ── Chargement ────────────────────────────────────────────────────────────
  function loadWatchlist() {
    if (!document.getElementById("sde-watchlist")) return;
    fetch("/watchlist")
      .then(function (r) {
        if (r.status === 401) return null;
        return r.json();
      })
      .then(function (data) { if (data) renderWatchlist(data); })
      .catch(function () {
        const c = document.getElementById("sde-watchlist");
        if (c) c.innerHTML =
          '<p class="text-center text-danger py-3" style="font-size:.8rem">Erreur de chargement.</p>';
      });
  }

  // ── Bouton ★ page d'analyse ───────────────────────────────────────────────
  function initPageButton() {
    const btn = document.getElementById("sde-wl-btn");
    if (!btn) return;

    btn.addEventListener("click", function () {
      const ticker  = this.dataset.ticker;
      const company = this.dataset.company;
      const isIn    = this.dataset.in === "true";

      if (isIn) {
        postJSON("/watchlist/remove", { ticker: ticker })
          .then(function (data) { if (data.ok) setButtonState(btn, false); });
      } else {
        postJSON("/watchlist/add", { ticker: ticker, company: company })
          .then(function (data) {
            if (data.ok) setButtonState(btn, true);
          });
      }
    });
  }

  function setButtonState(btn, isIn) {
    btn.dataset.in = isIn ? "true" : "false";
    btn.title      = isIn ? "Retirer de la watchlist" : "Ajouter à la watchlist";
    const icon = btn.querySelector("i");
    const span = btn.querySelector("span");
    if (isIn) {
      btn.style.background    = "#FEF3C7";
      btn.style.borderColor   = "#F59E0B";
      btn.style.color         = "#92400E";
      if (icon) icon.className = "bi bi-bookmark-star-fill me-1";
      if (span) span.textContent = "Dans la watchlist";
    } else {
      btn.style.background    = "";
      btn.style.borderColor   = "";
      btn.style.color         = "";
      if (icon) icon.className = "bi bi-bookmark-star me-1";
      if (span) span.textContent = "Ajouter";
    }
  }

  function syncPageButton(ticker, isIn) {
    const btn = document.getElementById("sde-wl-btn");
    if (btn && btn.dataset.ticker === ticker) setButtonState(btn, isIn);
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    initPageButton();

    // Charge la watchlist à l'ouverture du modal Bootstrap
    const modal = document.getElementById("sde-watchlist-modal");
    if (modal) {
      modal.addEventListener("show.bs.modal", loadWatchlist);
    }
  });
})();
