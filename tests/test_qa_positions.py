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
    market_mod.get_next_earnings = lambda t: None
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
market_mod.get_next_earnings = lambda t: {
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
