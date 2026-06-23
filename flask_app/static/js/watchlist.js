// watchlist.js — gestion AJAX watchlist (J7)
// Charge la sidebar, gère le bouton ★ sur la page d'analyse.

(function () {
  "use strict";

  const CSRF = (function () {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    const t = document.querySelector('meta[name="csrf-token"]');
    return t ? t.content : (m ? m[1] : "");
  })();

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF,
      },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  // ── Rendu sidebar ──────────────────────────────────────────────────────────
  function renderWatchlist(items) {
    const container = document.getElementById("sde-watchlist");
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML =
        '<p class="sde-caption">Aucune valeur suivie.</p>';
      return;
    }

    const ul = document.createElement("ul");
    ul.className = "list-unstyled mb-0";

    items.forEach(function (item) {
      const ticker  = (item.ticker || "").toUpperCase();
      const company = item.company || ticker;
      const li      = document.createElement("li");
      li.className  = "d-flex align-items-center gap-1 mb-1";
      li.dataset.ticker = ticker;
      li.innerHTML =
        '<a href="/analyze/' + encodeURIComponent(ticker) + '" ' +
        'class="sde-link text-truncate flex-grow-1 small" title="' + escHtml(company) + '">' +
        escHtml(ticker) +
        (company && company !== ticker
          ? ' <span class="text-muted" style="font-size:.7rem">· ' + escHtml(company) + '</span>'
          : '') +
        '</a>' +
        '<button class="btn-plain sde-wl-remove" data-ticker="' + escHtml(ticker) + '" ' +
        'title="Retirer" style="opacity:.5;font-size:.8rem">✕</button>';
      ul.appendChild(li);
    });

    container.innerHTML = "";
    container.appendChild(ul);

    // Boutons ✕ retirer
    container.querySelectorAll(".sde-wl-remove").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        const t = this.dataset.ticker;
        postJSON("/watchlist/remove", { ticker: t }).then(function (data) {
          if (data.ok) {
            const li = container.querySelector('li[data-ticker="' + t + '"]');
            if (li) li.remove();
            if (!container.querySelector("li")) {
              container.innerHTML =
                '<p class="sde-caption">Aucune valeur suivie.</p>';
            }
            syncPageButton(t, false);
          }
        });
      });
    });
  }

  // ── Chargement initial sidebar ─────────────────────────────────────────────
  function loadWatchlist() {
    if (!document.getElementById("sde-watchlist")) return;
    fetch("/watchlist")
      .then(function (r) {
        if (r.status === 401) {
          // Non connecté — ne rien faire (Jinja2 masque déjà la zone)
          return null;
        }
        return r.json();
      })
      .then(function (data) {
        if (data) renderWatchlist(data);
      })
      .catch(function () {
        const c = document.getElementById("sde-watchlist");
        if (c) c.innerHTML = '<p class="sde-caption text-danger">Erreur de chargement.</p>';
      });
  }

  // ── Bouton ★ sur la page d'analyse ────────────────────────────────────────
  function initPageButton() {
    const btn = document.getElementById("sde-wl-btn");
    if (!btn) return;

    btn.addEventListener("click", function () {
      const ticker  = this.dataset.ticker;
      const company = this.dataset.company;
      const isIn    = this.dataset.in === "true";

      if (isIn) {
        postJSON("/watchlist/remove", { ticker: ticker }).then(function (data) {
          if (data.ok) setButtonState(btn, false);
        });
      } else {
        postJSON("/watchlist/add", { ticker: ticker, company: company }).then(function (data) {
          if (data.ok) {
            setButtonState(btn, true);
            // Recharge la sidebar pour inclure le nouveau ticker
            fetch("/watchlist")
              .then(function (r) { return r.json(); })
              .then(renderWatchlist);
          }
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
      btn.classList.replace("btn-outline-secondary", "btn-warning");
      if (icon) icon.className = "bi bi-bookmark-star-fill me-1";
      if (span) span.textContent = "Dans la watchlist";
    } else {
      btn.classList.replace("btn-warning", "btn-outline-secondary");
      if (icon) icon.className = "bi bi-bookmark-star me-1";
      if (span) span.textContent = "Ajouter";
      // Met à jour la sidebar après suppression
      fetch("/watchlist")
        .then(function (r) { return r.json(); })
        .then(renderWatchlist);
    }
  }

  // Met à jour le bouton de la page si le ticker est retiré depuis la sidebar
  function syncPageButton(ticker, isIn) {
    const btn = document.getElementById("sde-wl-btn");
    if (btn && btn.dataset.ticker === ticker) setButtonState(btn, isIn);
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadWatchlist();
    initPageButton();
  });
})();
