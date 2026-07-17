# tests/test_risk.py — tests de la normalisation ATR des seuils, hors réseau.
#
# atr_pct(), seuils_adaptes() et drawdown_depuis_plus_haut() sont des
# fonctions PURES : historiques OHLC synthétiques à volatilité contrôlée.

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from portfolio.risk import (
    atr_pct, seuils_adaptes, drawdown_depuis_plus_haut,
    SL_ATR_MULT, TP_ATR_MULT,
)


def make_ohlc(vol_quotidienne: float, n: int = 60, seed: int = 5) -> pd.DataFrame:
    """
    Historique OHLC synthétique dont l'amplitude quotidienne (haut-bas)
    est contrôlée : vol_quotidienne = 0.05 → chaque bougie fait ~5% du cours.
    """
    np.random.seed(seed)
    close = pd.Series(100 * np.cumprod(1 + np.random.normal(0, vol_quotidienne / 3, n)))
    dates = pd.bdate_range("2026-04-01", periods=n)
    return pd.DataFrame({
        "Close": close.values,
        "High":  close.values * (1 + vol_quotidienne / 2),
        "Low":   close.values * (1 - vol_quotidienne / 2),
    }, index=dates)


CFG = {"stop_loss_pct": -20.0, "take_profit_pct": 15.0, "pnl_renforcer": -5.0}


# ── atr_pct : mesure bien l'amplitude quotidienne ──
atr_volatil = atr_pct(make_ohlc(0.05))   # bougies ~5%
atr_calme   = atr_pct(make_ohlc(0.01))   # bougies ~1%
assert 4.0 < atr_volatil < 7.0, f"ATR titre volatil attendu ~5%, obtenu {atr_volatil}"
assert 0.8 < atr_calme  < 1.5, f"ATR titre calme attendu ~1%, obtenu {atr_calme}"
# Historique trop court ou None → None (fallback seuils config)
assert atr_pct(make_ohlc(0.05, n=10)) is None
assert atr_pct(None) is None
print(f"✓ atr_pct : volatil {atr_volatil}%, calme {atr_calme}%, robuste aux cas limites")


# ── seuils_adaptes : le même titre volatil / calme donne des seuils opposés ──
s_vol   = seuils_adaptes(CFG, atr_volatil)
s_calme = seuils_adaptes(CFG, atr_calme)

# Titre volatil : stop = 2.5×ATR ≈ -13%, plus serré que la config -20
assert s_vol["adapte"] is True
assert abs(s_vol["stop_loss_pct"] - (-SL_ATR_MULT * atr_volatil)) < 0.1
assert -20 < s_vol["stop_loss_pct"] < -8

# Titre calme : 2.5×1% = -2.5 → borné au plancher 40% de la config (-8)
assert s_calme["stop_loss_pct"] == -8.0, f"attendu -8 (borne), obtenu {s_calme['stop_loss_pct']}"

# Le stop du titre calme est TOUJOURS plus serré que celui du volatil
assert s_calme["stop_loss_pct"] > s_vol["stop_loss_pct"]

# Jamais plus large que la config (perte max choisie par l'utilisateur)
s_extreme = seuils_adaptes(CFG, 15.0)   # ATR délirant de 15%/jour
assert s_extreme["stop_loss_pct"] >= -20.0

# Sans ATR → config inchangée, drapeau adapte=False
s_none = seuils_adaptes(CFG, None)
assert s_none["adapte"] is False and s_none["stop_loss_pct"] == -20.0
print("✓ seuils_adaptes : ATR appliqué, bornés autour de la config, fallback propre")


# ── drawdown_depuis_plus_haut : le trailing voit ce que le P&L ne voit pas ──
# Cours : monte de 100 à 140 puis retombe à 120 — position achetée à 100.
# P&L vs entrée : +20% (« tout va bien ») ; drawdown vs sommet : -14.3%.
n = 40
montee   = np.linspace(100, 140, 25)
descente = np.linspace(140, 120, 15)
close    = np.concatenate([montee, descente])
hist_dd  = pd.DataFrame(
    {"Close": close, "High": close * 1.01, "Low": close * 0.99},
    index=pd.bdate_range("2026-05-01", periods=n),
)
lots = [{"type": "achat", "date_achat": "2026-05-01"}]

hwm, dd = drawdown_depuis_plus_haut(hist_dd, lots, prix=120.0)
assert hwm == 140.0, f"plus haut attendu 140, obtenu {hwm}"
assert abs(dd - (-14.29)) < 0.1, f"drawdown attendu -14.3%, obtenu {dd}"

# Achat APRÈS le sommet → le plus haut est celui de la fenêtre de détention
hwm2, dd2 = drawdown_depuis_plus_haut(hist_dd, [{"type": "achat", "date_achat": "2026-06-19"}], 120.0)
assert hwm2 < 140.0, "le sommet d'avant l'achat ne doit pas compter"

# Le prix live peut être le sommet lui-même → drawdown nul
hwm3, dd3 = drawdown_depuis_plus_haut(hist_dd, lots, prix=145.0)
assert hwm3 == 145.0 and dd3 == 0.0

# Cas limites → (None, None), pas de crash
assert drawdown_depuis_plus_haut(None, lots, 100.0) == (None, None)
assert drawdown_depuis_plus_haut(hist_dd, [], 100.0) == (None, None)
assert drawdown_depuis_plus_haut(hist_dd, [{"type": "vente", "date_achat": "2026-05-02"}], 100.0) == (None, None)
print("✓ drawdown : sommet depuis l'achat, prix live inclus, cas limites propres")


# ── gap_significatif : seuil adapté à la volatilité du titre ──
from portfolio.risk import gap_significatif
# TMC (ATR 6.4) : -5% est du bruit pré-marché, -7% est significatif
assert gap_significatif(-5.0, 6.4) is False
assert gap_significatif(-7.0, 6.4) is True
# Titre calme (ATR 1.2) : le plancher de 2% s'applique
assert gap_significatif(-2.5, 1.2) is True
assert gap_significatif(-1.5, 1.2) is False
# Sans ATR : seuil prudent 3%
assert gap_significatif(2.9, None) is False and gap_significatif(3.1, None) is True
# Gap inconnu → jamais significatif (pas de faux déclenchement)
assert gap_significatif(None, 5.0) is False
print("✓ gap_significatif : seuil max(2%, 1×ATR), prudent sans données")


# ── Ligne Pré-marché dans le raisonnement du conseil ──
from portfolio.advisor import generate_advice
_hist_gap = make_ohlc(0.05)
_market   = {"price": float(_hist_gap["Close"].iloc[-1]), "rsi": 50.0,
             "history": _hist_gap, "gap_overnight": -7.2}
_summary  = {"pnl_pct": 5.0, "total_shares": 100, "cout_moyen": 100.0,
             "lots": [{"type": "achat", "date_achat": "2026-04-01"}]}
_snap     = {"score_global": 50.0, "recommandation": "NEUTRE",
             "signals_tech": [], "signals_fund": []}
adv = generate_advice(_summary, _market, _snap)
assert "Pré-marché : -7.2%" in adv["raisonnement"], "la ligne gap doit apparaître"
assert "baissier" in adv["raisonnement"]
# Sans gap : pas de ligne (la clé absente ne doit rien afficher)
_market.pop("gap_overnight")
adv2 = generate_advice(_summary, _market, _snap)
assert "Pré-marché" not in adv2["raisonnement"]
print("✓ conseil : ligne Pré-marché présente avec gap, absente sans")


# ── Surclassement chandelier : plus de texte contradictoire ──
# Reproduction du cas TMC 14.07.2026 : base TENIR ('maintien de la
# position') surclassée en ALLÉGER par un pattern baissier — la première
# phrase contredisait le badge. Le texte doit maintenant être cohérent.
# Date dynamique (hier) : le garde-fou de fraîcheur périme les patterns
# de plus de 2 séances — une date en dur casserait le test avec le temps
import datetime as _dt
_candle_bear = {"signal": "bearish", "pattern": "Étoile du soir",
                "description": "",
                "date": (_dt.date.today() - _dt.timedelta(days=1)).strftime("%d.%m.%Y")}
_m_tmc = {"price": 3.99, "rsi": 45.0, "history": make_ohlc(0.06)}
_s_tmc = {"pnl_pct": -0.5, "total_shares": 10768, "cout_moyen": 4.01,
          "lots": [{"type": "achat", "date_achat": "2026-06-01"}]}
_snap_tmc = {"score_global": 41.4, "recommandation": "VENDRE",
             "signals_tech": [], "signals_fund": []}
adv_tmc = generate_advice(_s_tmc, _m_tmc, _snap_tmc, candle_info=_candle_bear)
assert adv_tmc["action"] == "ALLÉGER"
assert adv_tmc["quantite_suggeree"] == round(10768 * 0.25)   # 2692
assert "maintien de la position" not in adv_tmc["raisonnement"], \
    "le texte TENIR ne doit plus contredire le badge ALLÉGER"
assert "allégement préventif de 25%" in adv_tmc["raisonnement"]
print("✓ surclassement chandelier : texte cohérent avec l'action (cas TMC 14.07)")

# INVALIDATION par le rebond du jour : même pattern baissier, mais le
# titre rebondit de +5.5% sur la séance en cours → le pattern de la
# veille est contredit, PAS d'allégement (cas du recalcul TMC 14.07).
# prix = plus haut de l'historique : neutralise la règle trailing
# (drawdown 0) pour isoler la règle chandelier testée ici.
_prix_hwm = float(_m_tmc["history"]["Close"].max()) * 1.01
_m_rebond = {**_m_tmc, "price": _prix_hwm, "var_1d": 5.5}
_s_rebond = {**_s_tmc, "pnl_pct": 5.0}
adv_rebond = generate_advice(_s_rebond, _m_rebond, _snap_tmc, candle_info=_candle_bear)
assert adv_rebond["action"] == "TENIR", \
    f"rebond +5.5% doit invalider le pattern baissier, obtenu {adv_rebond['action']}"
assert "signal probablement invalidé" in adv_rebond["raisonnement"]

# Petit rebond (+1%) : sous le seuil de 2% → l'allégement reste conseillé
_m_petit = {**_m_tmc, "var_1d": 1.0}
adv_petit = generate_advice(_s_tmc, _m_petit, _snap_tmc, candle_info=_candle_bear)
assert adv_petit["action"] == "ALLÉGER"

# var_1d absent (vieux snapshot) → comportement historique conservé
_m_sans = {k: v for k, v in _m_tmc.items() if k != "var_1d"}
adv_sans = generate_advice(_s_tmc, _m_sans, _snap_tmc, candle_info=_candle_bear)
assert adv_sans["action"] == "ALLÉGER"
print("✓ invalidation : rebond ≥2% → TENIR, petit rebond ou var inconnu → ALLÉGER")


# MÉMOIRE DU JOUR : l'utilisateur a suivi l'ALLÉGER (vente enregistrée
# aujourd'hui) → le même pattern ne doit PAS re-suggérer une réduction
# (vécu TMC 15.07 : ALLÉGER 2692 suivi → nouvel ALLÉGER 2019 sur le restant)
from datetime import date as _date
_s_vendu = {"pnl_pct": 2.3, "total_shares": 8076, "cout_moyen": 4.01,
            "lots": [
                {"type": "achat", "date_achat": "2026-06-01", "quantite": 10768},
                {"type": "vente", "date_achat": str(_date.today()), "quantite": 2692},
            ]}
_m_calme = {**_m_tmc, "var_1d": -1.4}     # pas de rebond → invalidation inactive
adv_vendu = generate_advice(_s_vendu, _m_calme, _snap_tmc, candle_info=_candle_bear)
assert adv_vendu["action"] == "TENIR", \
    f"après une vente du jour, pas de nouvel ALLÉGER — obtenu {adv_vendu['action']}"
assert "allégement déjà réalisé aujourd'hui (2692 actions)" in adv_vendu["raisonnement"]

# Vente d'HIER → le signal peut de nouveau suggérer (nouvelle journée)
_s_hier = {**_s_vendu, "lots": [
    {"type": "achat", "date_achat": "2026-06-01", "quantite": 10768},
    {"type": "vente", "date_achat": "2026-07-14", "quantite": 2692},
]}
adv_hier = generate_advice(_s_hier, _m_calme, _snap_tmc, candle_info=_candle_bear)
assert adv_hier["action"] == "ALLÉGER"
print("✓ mémoire du jour : vente aujourd'hui → pas de nouvel ALLÉGER ; hier → normal")


# ── Ré-entrée après clôture : le ticker n'est plus orphelin ──
# Position entièrement vendue HIER + signal fort → conseil ACHETER
# (avant : summary existait → monde 'sans position' inaccessible → jamais
# de conseil de ré-entrée)
_s_clos = {"pnl_pct": 5.2, "total_shares": 0, "cout_moyen": 4.01,
           "pnl_realise": 215.36, "position_fermee": True,
           "lots": [
               {"type": "achat", "date_achat": "2026-06-01", "quantite": 10768, "prix_achat": 4.01},
               {"type": "vente", "date_achat": "2026-07-14", "quantite": 10768, "prix_achat": 4.03},
           ]}
_snap_fort = {"score_global": 62.0, "recommandation": "ACHETER",
              "signals_tech": [], "signals_fund": []}
adv_reentree = generate_advice(_s_clos, _m_calme, _snap_fort)
assert adv_reentree["action"] == "ACHETER", \
    f"position clôturée + signal fort → ré-entrée ACHETER, obtenu {adv_reentree['action']}"
assert "Position clôturée le 14.07 à 4.03 $" in adv_reentree["raisonnement"]
assert "+215.36 $" in adv_reentree["raisonnement"]

# Clôture AUJOURD'HUI → pas de ré-entrée le même jour, même signal fort
_s_clos_auj = {**_s_clos, "lots": [
    {"type": "achat", "date_achat": "2026-06-01", "quantite": 10768, "prix_achat": 4.01},
    {"type": "vente", "date_achat": str(_date.today()), "quantite": 10768, "prix_achat": 4.03},
]}
adv_auj = generate_advice(_s_clos_auj, _m_calme, _snap_fort)
assert adv_auj["action"] == "SURVEILLER"
assert "pas de ré-entrée le même jour" in adv_auj["raisonnement"]

# Clôturée + signal faible → SURVEILLER avec le contexte de sortie
adv_faible = generate_advice(_s_clos, _m_calme, _snap_tmc)
assert adv_faible["action"] == "SURVEILLER"
assert "Position clôturée" in adv_faible["raisonnement"]
print("✓ ré-entrée : clôturée+signal fort → ACHETER, le même jour → SURVEILLER, faible → SURVEILLER")


# ── Trésorerie : ACHETER/RENFORCER contraints par le cash suivi ──
# Ré-entrée avec signal fort mais 2 $ de cash pour un cours à ~100 $
# → SURVEILLER (un conseil inapplicable est pire que pas de conseil)
adv_sans_cash = generate_advice(_s_clos, _m_calme, _snap_fort, cash_dispo=2.0)
assert adv_sans_cash["action"] == "SURVEILLER"
assert "trésorerie suivie insuffisante" in adv_sans_cash["raisonnement"]

# Ré-entrée avec cash → ACHETER, trésorerie et nb d'actions affichés
adv_cash = generate_advice(_s_clos, _m_calme, _snap_fort, cash_dispo=10820.0)
assert adv_cash["action"] == "ACHETER"
assert "Trésorerie suivie disponible" in adv_cash["raisonnement"]

# RENFORCER plafonné : 25% de 10768 = 2692, mais cash pour ~50 actions
# (le plafond se calcule sur market['price'] — le cours actuel du titre)
_s_creux  = {"pnl_pct": -8.0, "total_shares": 10768, "cout_moyen": 4.01,
             "lots": [{"type": "achat", "date_achat": "2026-06-01", "quantite": 10768}]}
_m_creux  = {**_m_tmc, "rsi": 35.0}
_snap_ach = {"score_global": 62.0, "recommandation": "ACHETER",
             "signals_tech": [], "signals_fund": []}
adv_plaf = generate_advice(_s_creux, _m_creux, _snap_ach,
                           cash_dispo=_m_creux["price"] * 50.5)
assert adv_plaf["action"] == "RENFORCER"
assert adv_plaf["quantite_suggeree"] == 50, \
    f"quantité plafonnée à 50 par le cash, obtenu {adv_plaf['quantite_suggeree']}"
assert "limitée par la trésorerie" in adv_plaf["raisonnement"]

# RENFORCER sans cash du tout → TENIR avec explication
adv_zero = generate_advice(_s_creux, _m_creux, _snap_ach, cash_dispo=0.0)
assert adv_zero["action"] == "TENIR"
assert "trésorerie suivie insuffisante" in adv_zero["raisonnement"]

# cash_dispo=None (inconnu) → aucun bridage (comportement historique)
adv_libre = generate_advice(_s_creux, _m_creux, _snap_ach, cash_dispo=None)
assert adv_libre["action"] == "RENFORCER"
assert adv_libre["quantite_suggeree"] == 2692
print("✓ trésorerie : ACHETER bloqué sans cash, RENFORCER plafonné/bloqué, None → libre")


# ── Cohérence avec l'évaluateur : bande TENIR vol-normalisée ──
from portfolio.evaluator import _seuil_tenir
assert _seuil_tenir(20) == 13.4                       # sans ATR : base 3% historique
assert _seuil_tenir(20, atr=5.0) == round(5.0 * 20**0.5, 1)   # ±22.4% pour un titre à 5%
assert _seuil_tenir(1, atr=15.0) == 8.0               # ATR extrême borné à 8
assert _seuil_tenir(1, atr=0.5)  == 2.0               # ATR minuscule borné à 2
print("✓ _seuil_tenir : bande TENIR proportionnelle à l'ATR, bornée [2;8]")

# ── Double confirmation des sorties : pattern seul ≠ allégement ──
# Marché porteur (régime haussier) + score correct (58) + pattern baissier
# frais → PAS d'allégement (les signaux baissiers isolés sont peu fiables
# en marché haussier — attribution backtest : 27% sur TMC)
_snap_porteur = {"score_global": 58.0, "recommandation": "ACHETER",
                 "signals_tech": [], "signals_fund": [],
                 "market_regime": {"regime": "haussier"}}
adv_porteur = generate_advice(_s_tmc, _m_calme, _snap_porteur, candle_info=_candle_bear)
assert adv_porteur["action"] == "TENIR", \
    f"marché porteur + score 58 → pas de sortie sur pattern isolé, obtenu {adv_porteur['action']}"
assert "double confirmation requise" in adv_porteur["raisonnement"]

# Régime BAISSIER + même score → le pattern est confirmé → ALLÉGER
_snap_baissier = {**_snap_porteur, "market_regime": {"regime": "baissier"}}
adv_baissier = generate_advice(_s_tmc, _m_calme, _snap_baissier, candle_info=_candle_bear)
assert adv_baissier["action"] == "ALLÉGER"

# Score < 45 (zone VENDRE) + régime haussier → confirmé par le score → ALLÉGER
# (_snap_tmc : score 41.4 — c'est pour ça que les tests historiques passent)
adv_score_bas = generate_advice(_s_tmc, _m_calme, _snap_tmc, candle_info=_candle_bear)
assert adv_score_bas["action"] == "ALLÉGER"
print("✓ double confirmation : porteur+score OK → TENIR ; régime baissier ou score <45 → ALLÉGER")


# ── Fraîcheur du pattern : un chandelier de > 3 jours n'escalade plus ──
# L'Étoile du soir du 13.07 déclenchait ALLÉGER tous les jours suivants
_candle_vieux = {**_candle_bear,
                 "date": (_date.today() - __import__("datetime").timedelta(days=4)).strftime("%d.%m.%Y")}
adv_vieux = generate_advice(_s_tmc, _m_calme, _snap_tmc, candle_info=_candle_vieux)
assert adv_vieux["action"] == "TENIR", \
    f"pattern de 4 jours ne doit plus escalader, obtenu {adv_vieux['action']}"
assert "signal périmé" in adv_vieux["raisonnement"]
# Pattern d'il y a 2 jours : escalade normale
_candle_frais = {**_candle_bear,
                 "date": (_date.today() - __import__("datetime").timedelta(days=2)).strftime("%d.%m.%Y")}
adv_frais = generate_advice(_s_tmc, _m_calme, _snap_tmc, candle_info=_candle_frais)
assert adv_frais["action"] == "ALLÉGER"
print("✓ fraîcheur pattern : > 3 jours → information seulement, ≤ 3 jours → escalade")


# ── Repli exceptionnel : la chute du 16.07 rejouée ──
# TMC -6.8% en séance (≥ 1×ATR ~6%), RSI 34, score 57, cash dispo →
# RENFORCER (l'utilisateur avait dû acheter SANS conseil ce jour-là :
# la règle P&L ratait les soldes du marché)
_m_krach = {**_m_tmc, "price": 3.83, "var_1d": -6.8, "rsi": 34.0}
_s_krach = {"pnl_pct": -4.6, "total_shares": 8076, "cout_moyen": 4.01,
            "lots": [{"type": "import", "date_achat": "2026-07-08", "quantite": 10768}]}
_snap_krach = {"score_global": 57.0, "recommandation": "ACHETER",
               "signals_tech": [], "signals_fund": []}
adv_krach = generate_advice(_s_krach, _m_krach, _snap_krach, cash_dispo=10800.0)
assert adv_krach["action"] == "RENFORCER", \
    f"chute ≥1×ATR + RSI bas + score OK + cash → RENFORCER, obtenu {adv_krach['action']}"
assert "Repli exceptionnel" in adv_krach["raisonnement"]
assert adv_krach["quantite_suggeree"] == round(8076 * 0.25)   # 2019, cash suffisant

# Chute dans le bruit (-3% pour un ATR ~6%) → pas de repli exceptionnel
adv_bruit = generate_advice(_s_krach, {**_m_krach, "var_1d": -3.0},
                            _snap_krach, cash_dispo=10800.0)
assert adv_bruit["action"] != "RENFORCER"

# Score effondré (41 < 45) pendant la chute → pas d'achat du couteau qui tombe
adv_couteau = generate_advice(_s_krach, _m_krach,
                              {**_snap_krach, "score_global": 41.0,
                               "recommandation": "VENDRE"}, cash_dispo=10800.0)
assert adv_couteau["action"] != "RENFORCER"

# Sans trésorerie → TENIR avec explication (pas de conseil inapplicable)
adv_fauche = generate_advice(_s_krach, _m_krach, _snap_krach, cash_dispo=1.0)
assert adv_fauche["action"] == "TENIR"
assert "trésorerie suivie insuffisante" in adv_fauche["raisonnement"]
print("✓ repli exceptionnel : le 16.07 rejoué → RENFORCER ; bruit/score bas/sans cash → non")


# ── Point de contrôle post-ouverture : marqueur dans le raisonnement ──
_m_po = {**_m_krach, "post_ouverture": True}
adv_po = generate_advice(_s_krach, _m_po, _snap_krach, cash_dispo=10800.0)
assert "après la première heure de séance" in adv_po["raisonnement"]
_m_sans_po = {k: v for k, v in _m_po.items() if k != "post_ouverture"}
adv_spo = generate_advice(_s_krach, _m_sans_po, _snap_krach, cash_dispo=10800.0)
assert "après la première heure de séance" not in adv_spo["raisonnement"]
print("✓ post-ouverture : marqueur présent avec le flag, absent sans")


# ── etat_compte : la métrique objectif (compte total) et son benchmark ──
from portfolio.positions import etat_compte
# Scénario réel admin : import 10768 @ 4.01, vente 2692 @ 4.02, cours 4.13
lots_admin = [
    {"ticker": "TMC", "type": "import", "quantite": 10768, "prix_achat": 4.01},
    {"ticker": "TMC", "type": "vente",  "quantite": 2692,  "prix_achat": 4.02},
]
etat = etat_compte(lots_admin, {"TMC": 4.13})
assert etat["cash"] == round(2692 * 4.02, 2)                       # ventes − 0 achat
assert etat["valeur_positions"] == round(8076 * 4.13, 2)           # actions restantes
assert etat["total"] == round(etat["valeur_positions"] + etat["cash"], 2)
assert etat["buy_hold"] == round(10768 * 4.13, 2)                  # imports conservés
# L'écart mesure l'effet des conseils : vendu à 4.02, cours à 4.13 → coût
assert etat["total"] - etat["buy_hold"] < 0

# Réinvestissement : achat 1000 @ 4.00 financé par le cash suivi
lots_reinv = lots_admin + [
    {"ticker": "TMC", "type": "achat", "quantite": 1000, "prix_achat": 4.00}]
etat2 = etat_compte(lots_reinv, {"TMC": 4.13})
assert etat2["cash"] == round(2692 * 4.02 - 1000 * 4.00, 2)        # cash décrémenté
assert etat2["valeur_positions"] == round(9076 * 4.13, 2)
# PAS de double comptage : le total ne bouge que par l'écart prix (4.13 vs 4.00)
assert abs(etat2["total"] - etat["total"] - 1000 * 0.13) < 0.01
# Le B&H ignore achats/ventes : inchangé
assert etat2["buy_hold"] == etat["buy_hold"]

# Convention violée (achat sans cash) → cash planché à 0, pas de total négatif
etat3 = etat_compte([{"ticker": "X", "type": "achat", "quantite": 100, "prix_achat": 10}],
                    {"X": 10})
assert etat3["cash"] == 0.0 and etat3["total"] == 1000.0
print("✓ etat_compte : compte total exact, pas de double comptage, B&H stable")

print("\n✓ Tous les tests test_risk.py sont OK (hors réseau)")
