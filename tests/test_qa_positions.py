# tests/test_qa_positions.py — Q&A scopée positions/portefeuille, hors réseau.
#
# Demandé le 18.08.2026 : les questions "je sors de FCEL pour renforcer
# TMC ?" posées en session de dev n'étaient pas du code, de l'analyse de
# données que SDE peut faire lui-même. Portée volontairement restreinte
# (1 ticker choisi dans un menu, ou "tout le portefeuille") — jamais de
# détection de ticker depuis du texte libre, jamais de données chargées
# hors de ce qui a été explicitement choisi. Ici : le backend ne doit
# JAMAIS appeler Groq si la portée demandée n'est pas valide, et doit
# répondre proprement (pas de crash) à chaque étape.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import analysis.qa_positions as qa
import portfolio.positions as positions_mod
import watchlist.watchlist as watchlist_mod
import data.market as market_mod
import portfolio.advisor as advisor_mod
import portfolio.evaluator as evaluator_mod

qa.LLM_ENABLED   = True
qa.GROQ_API_KEY  = "fake-key"


def _reset_mocks():
    positions_mod.get_positions = lambda u, t=None: []
    watchlist_mod.get_watchlist = lambda u: []
    market_mod.get_live_price   = lambda t: {}
    market_mod.get_next_earnings = lambda t, retro_jours=3: None
    positions_mod.get_portfolio_summary = lambda u, t, p: None
    advisor_mod.get_today_advice   = lambda u, t: None
    advisor_mod.get_advice_history = lambda u, t, limit=1: []
    evaluator_mod.get_ticker_stats_bulk = lambda u, ts: {}


# ── tickers_disponibles : union positions + watchlist, dédupliquée triée ──
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [
    {"ticker": "TMC"}, {"ticker": "TMC"}, {"ticker": "FCEL"},
]
watchlist_mod.get_watchlist = lambda u: [{"ticker": "FCEL"}, {"ticker": "ITG"}]
assert qa.tickers_disponibles("admin") == ["FCEL", "ITG", "TMC"]
print("✓ tickers_disponibles : union positions+watchlist, dédupliquée et triée")


# ── _bloc_ticker : assemble tout le contexte attendu ──
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [
    {"ticker": "TMC", "company": "TMC the metals company", "type": "achat",
     "quantite": 8152, "prix_achat": 3.97},
]
market_mod.get_live_price = lambda t: {"price": 3.77, "var_1d": -5.99}
positions_mod.get_portfolio_summary = lambda u, t, p: {
    "total_shares": 8152, "cout_moyen": 3.97, "pnl_position_pct": -5.08,
    "pnl_pct": -4.1, "position_fermee": False,
}
advisor_mod.get_today_advice = lambda u, t: {
    "date_conseil": "2026-08-18", "action": "TENIR", "score_sde": 61,
    "raisonnement": "Signal SDE ACHETER (61/100) — maintien de la position.",
}
evaluator_mod.get_ticker_stats_bulk = lambda u, ts: {
    "TMC": {"total": 31, "bons": 25, "taux_pct": 80.6},
}
market_mod.get_next_earnings = lambda t, retro_jours=3: {
    "date": "2026-08-13", "jours": -5, "statut": "publie",
    "eps_estimate": -0.06, "eps_actual": -0.14,
}
bloc = qa._bloc_ticker("admin", "TMC")
assert "TMC" in bloc and "3.77$" in bloc
assert "8152" in bloc and "3.97$" in bloc and "-5.1%" in bloc
assert "TENIR" in bloc and "61/100" in bloc
assert "80.6%" in bloc and "31 conseils" in bloc
assert "BPA -0.14$" in bloc and "-0.06$" in bloc
print("✓ _bloc_ticker : prix, position, conseil, fiabilité, résultats — tous présents")

# Aucune donnée du tout -> None (pas de bloc vide envoyé au LLM)
_reset_mocks()
bloc_vide = qa._bloc_ticker("admin", "XYZ")
assert bloc_vide is None
print("✓ _bloc_ticker : aucune donnée -> None")

# ── Fenêtre earnings élargie (retro_jours=100) pour la Q&A ──
# Signalé le 18.08.2026 : "quel est le dernier résultat publié ?" refusé
# car get_next_earnings() par défaut (retro_jours=3, pensé pour le badge
# qui doit s'effacer vite) ne remontait plus jusqu'aux résultats de TMC
# publiés 5 jours plus tôt. La Q&A doit pouvoir répondre sur tout le
# dernier trimestre, pas seulement les derniers jours.
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [{"ticker": "TMC", "type": "achat"}]
market_mod.get_live_price = lambda t: {"price": 3.77, "var_1d": -1.0}
captured_kwargs = {}


def _earnings_capture(t, retro_jours=3):
    captured_kwargs["retro_jours"] = retro_jours
    return {"date": "2026-08-13", "jours": -5, "statut": "publie",
            "eps_estimate": -0.06, "eps_actual": -0.14}


market_mod.get_next_earnings = _earnings_capture
bloc_earn = qa._bloc_ticker("admin", "TMC")
assert captured_kwargs["retro_jours"] == 100, \
    "la Q&A doit interroger avec une fenêtre bien plus large que le badge (3j)"
assert "BPA -0.14$" in bloc_earn
print("✓ _bloc_ticker : interroge get_next_earnings avec retro_jours=100 (pas le défaut 3j du badge)")


# ── _contexte : scope ticker, portée refusée si hors positions/watchlist ──
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [{"ticker": "TMC"}]
market_mod.get_live_price = lambda t: {"price": 3.77, "var_1d": -1.0}
ctx, err = qa._contexte("admin", "ticker", "AAPL")
assert ctx is None and "positions" in err.lower()
print("✓ _contexte : ticker hors positions/watchlist -> refusé, pas de contexte assemblé")

ctx2, err2 = qa._contexte("admin", "ticker", "tmc")   # minuscule -> normalisé
assert ctx2 is not None and err2 is None
print("✓ _contexte : ticker valide (insensible à la casse) -> contexte assemblé")


# ── _contexte : scope portefeuille, positions clôturées exclues ──
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [
    {"ticker": "TMC"}, {"ticker": "FCEL"},
]
market_mod.get_live_price = lambda t: {"price": 10.0, "var_1d": 0.0}


def _summary_par_ticker(u, t, p):
    if t == "TMC":
        return {"total_shares": 100, "cout_moyen": 9.0, "pnl_position_pct": 5.0,
                "pnl_pct": 5.0, "position_fermee": False}
    return {"total_shares": 0, "cout_moyen": 9.0, "pnl_position_pct": None,
            "pnl_pct": 10.0, "position_fermee": True}   # FCEL clôturé


positions_mod.get_portfolio_summary = _summary_par_ticker
ctx3, err3 = qa._contexte("admin", "portefeuille", None)
assert ctx3 is not None and err3 is None
assert "TMC" in ctx3 and "FCEL" not in ctx3
print("✓ _contexte : scope portefeuille -> seules les positions OUVERTES incluses")

# Aucune position ouverte -> erreur explicite
positions_mod.get_portfolio_summary = lambda u, t, p: {
    "total_shares": 0, "position_fermee": True, "pnl_position_pct": None, "pnl_pct": 0,
    "cout_moyen": 1.0,
}
ctx4, err4 = qa._contexte("admin", "portefeuille", None)
assert ctx4 is None and "aucune position" in err4.lower()
print("✓ _contexte : aucune position ouverte -> erreur explicite")


# ── donnees_affichage : chiffres clés structurés pour l'UI ──
# Signalé le 18.08.2026 : avoir les chiffres sous les yeux (ligne pour
# un ticker, tableau pour le portefeuille), pas seulement dans la
# réponse texte du LLM. Même source de données que _bloc_ticker
# (_donnees_ticker), juste formatée en champs plutôt qu'en texte.
_reset_mocks()
positions_mod.get_positions = lambda u, t=None: [
    {"ticker": "TMC", "company": "TMC the metals company"},
]
market_mod.get_live_price = lambda t: {"price": 3.77, "var_1d": -5.99}
positions_mod.get_portfolio_summary = lambda u, t, p: {
    "total_shares": 8152, "cout_moyen": 3.97, "pnl_position_pct": -5.08,
    "pnl_pct": -4.1, "position_fermee": False, "currency": "USD",
}
advisor_mod.get_today_advice = lambda u, t: {
    "date_conseil": "2026-08-18", "action": "TENIR", "score_sde": 60.6,
    "raisonnement": "...",
}
evaluator_mod.get_ticker_stats_bulk = lambda u, ts: {
    "TMC": {"total": 35, "bons": 31, "taux_pct": 88.6},
}
d = qa.donnees_affichage("admin", "ticker", "tmc")   # minuscule -> normalisé
assert d["ok"] is True and len(d["lignes"]) == 1
ligne = d["lignes"][0]
assert ligne["ticker"] == "TMC" and ligne["sym"] == "$"
assert ligne["price"] == 3.77 and ligne["var_1d"] == -5.99
assert ligne["shares"] == 8152 and ligne["cout_moyen"] == 3.97
assert ligne["pnl_position_pct"] == -5.08
assert ligne["action"] == "TENIR" and ligne["score"] == 60.6
assert ligne["taux_pct"] == 88.6 and ligne["total_evalues"] == 35
print("✓ donnees_affichage : scope ticker -> une ligne avec tous les chiffres clés")

# Ticker hors portée -> erreur, mêmes garde-fous que _contexte
d_refus = qa.donnees_affichage("admin", "ticker", "AAPL")
assert d_refus["ok"] is False
print("✓ donnees_affichage : ticker hors portée -> refusé (mêmes garde-fous que la Q&A)")

# scope portefeuille -> une ligne par position OUVERTE, clôturées exclues
positions_mod.get_positions = lambda u, t=None: [
    {"ticker": "TMC", "company": "TMC"}, {"ticker": "FCEL", "company": "FCEL"},
]
positions_mod.get_portfolio_summary = _summary_par_ticker   # TMC ouverte, FCEL clôturée (défini plus haut)
d_pf = qa.donnees_affichage("admin", "portefeuille", None)
assert d_pf["ok"] is True
tickers_lignes = [l["ticker"] for l in d_pf["lignes"]]
assert tickers_lignes == ["TMC"]
print("✓ donnees_affichage : scope portefeuille -> une ligne par position ouverte, clôturées exclues")


# ── ask() : validations avant tout appel réseau ──
_reset_mocks()
assert qa.ask("admin", "ticker", "TMC", "")["ok"] is False   # question vide
assert qa.ask("admin", "ticker", "TMC", "x" * 501)["ok"] is False   # trop longue

qa.LLM_ENABLED = False
r = qa.ask("admin", "ticker", "TMC", "une question")
assert r["ok"] is False and "désactivée" in r["error"].lower()
qa.LLM_ENABLED = True

qa.GROQ_API_KEY = ""
r2 = qa.ask("admin", "ticker", "TMC", "une question")
assert r2["ok"] is False and "clé" in r2["error"].lower()
qa.GROQ_API_KEY = "fake-key"
print("✓ ask : question vide/trop longue/LLM désactivé/clé absente -> refus avant tout appel réseau")

# Portée invalide -> erreur de _contexte propagée, jamais d'appel Groq
_reset_mocks()


def _boom(*a, **k):
    raise AssertionError("Groq ne doit jamais être appelé si la portée est invalide")


qa.requests.post = _boom
r3 = qa.ask("admin", "ticker", "AAPL", "une question")
assert r3["ok"] is False
print("✓ ask : portée invalide -> Groq jamais appelé")


# ── ask() : chemin de succès, prompt contient bien le contexte et la question ──
positions_mod.get_positions = lambda u, t=None: [{"ticker": "TMC"}]
market_mod.get_live_price = lambda t: {"price": 3.77, "var_1d": -1.0}
positions_mod.get_portfolio_summary = lambda u, t, p: {
    "total_shares": 100, "cout_moyen": 4.0, "pnl_position_pct": -5.0,
    "pnl_pct": -4.0, "position_fermee": False,
}

captured = {}


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "Réponse factuelle sur TMC."}}]}


def _fake_post(url, headers=None, json=None, timeout=None):
    captured["url"] = url
    captured["payload"] = json
    return _FakeResp()


qa.requests.post = _fake_post
r4 = qa.ask("admin", "ticker", "TMC", "je renforce maintenant ?")
assert r4 == {"ok": True, "reponse": "Réponse factuelle sur TMC."}
assert captured["payload"]["model"]
assert captured["payload"]["reasoning_effort"] == "medium"
assert "TMC" in captured["payload"]["messages"][0]["content"]   # contexte dans le system prompt
assert captured["payload"]["messages"][1]["content"] == "je renforce maintenant ?"
print("✓ ask : chemin de succès — contexte + question transmis, réponse extraite correctement")

# Échec réseau -> message générique, pas de traceback exposé
def _fake_post_boom(*a, **k):
    raise RuntimeError("Groq down")


qa.requests.post = _fake_post_boom
r5 = qa.ask("admin", "ticker", "TMC", "je renforce maintenant ?")
assert r5["ok"] is False and "indisponible" in r5["error"].lower()
print("✓ ask : échec réseau -> message générique, dégradation propre")

print("\n✓ Tous les tests test_qa_positions.py sont OK (hors réseau)")
