# portfolio/risk.py — normalisation des seuils de conseil par la volatilité
#
# Problème corrigé : les seuils du conseil étaient en % FIXES pour tous les
# titres (stop -20%, TP +15%…). Or -20% est du bruit courant sur une small
# cap à 5%/jour de volatilité, et une catastrophe déjà consommée sur un
# titre calme à 1%/jour. Le même chiffre signifie deux choses opposées.
#
# La correction canonique : exprimer les seuils en MULTIPLES d'ATR
# (Average True Range = amplitude moyenne quotidienne réelle du titre).
# "Stop à 2.5×ATR" veut dire la même chose partout : « le titre a bougé
# bien au-delà de son bruit normal ».
#
# Garde-fou : les seuils configurés par l'utilisateur (advisor_config)
# restent le CENTRE — l'ATR ne fait qu'adapter autour, dans des bornes.
# Le stop ne peut jamais être plus large que la config (plancher de perte
# maximale), ni plus serré que 40% de celle-ci.

import numpy as np
import pandas as pd

# Multiples d'ATR — conventions classiques de money management
SL_ATR_MULT    = 2.5   # stop loss : 2.5 × le bruit quotidien
TP_ATR_MULT    = 3.0   # objectif : il faut plus de chemin que de risque
RENF_ATR_MULT  = 1.0   # renforcer sur faiblesse : ~1 jour de bruit défavorable
TRAIL_ATR_MULT = 2.0   # repli depuis le plus haut déclenchant la sécurisation


def atr_pct(hist: pd.DataFrame, period: int = 14):
    """
    ATR(14) exprimé en % du dernier cours — l'amplitude quotidienne
    « normale » du titre. Fonction PURE. None si historique inexploitable
    (l'appelant retombe alors sur les seuils % fixes de la config).

    True Range = max(haut-bas, |haut-clôture veille|, |bas-clôture veille|)
    — la 2e et 3e composante capturent les gaps d'ouverture.
    """
    try:
        if hist is None or len(hist) < period + 1:
            return None
        high, low, close = hist["High"], hist["Low"], hist["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr     = tr.rolling(period).mean().iloc[-1]
        dernier = float(close.iloc[-1])
        if pd.isna(atr) or dernier <= 0:
            return None
        return round(float(atr) / dernier * 100, 2)
    except Exception:
        return None


def seuils_adaptes(cfg: dict, atr: float | None) -> dict:
    """
    Convertit les seuils % de la config en seuils adaptés à la volatilité.
    Fonction PURE. Sans ATR (None) → seuils config inchangés.

    np.clip borne chaque seuil autour de la valeur configurée :
      stop  : [-|cfg| ; -0.4×|cfg|]  — jamais plus large que la config
                                       (perte max choisie par l'utilisateur),
                                       jamais plus serré que 40% de celle-ci
      tp    : [0.6×cfg ; 1.6×cfg]
      renf  : [-1.6×|cfg| ; -0.6×|cfg|]

    Ex. TMC (ATR 5%) : stop 2.5×5 = -12.5% (au lieu de -20 uniforme)
        Titre calme (ATR 1%) : stop 2.5×1 = 2.5 → borné à -8 (0.4×20)
    """
    out = {
        "stop_loss_pct":   float(cfg["stop_loss_pct"]),
        "take_profit_pct": float(cfg["take_profit_pct"]),
        "pnl_renforcer":   float(cfg["pnl_renforcer"]),
        "atr_pct":         atr,
        "adapte":          False,
    }
    if atr is None or atr <= 0:
        return out

    sl_cfg, tp_cfg, rf_cfg = (abs(out["stop_loss_pct"]),
                              out["take_profit_pct"],
                              abs(out["pnl_renforcer"]))
    out["stop_loss_pct"]   = -round(float(np.clip(SL_ATR_MULT   * atr, 0.4 * sl_cfg, sl_cfg)), 1)
    out["take_profit_pct"] =  round(float(np.clip(TP_ATR_MULT   * atr, 0.6 * tp_cfg, 1.6 * tp_cfg)), 1)
    out["pnl_renforcer"]   = -round(float(np.clip(RENF_ATR_MULT * atr, 0.6 * rf_cfg, 1.6 * rf_cfg)), 1)
    out["adapte"]          = True
    return out


def drawdown_depuis_plus_haut(hist: pd.DataFrame, lots: list, prix: float):
    """
    Repli du cours actuel par rapport au PLUS HAUT atteint depuis
    l'ouverture de la position (high-water mark). Fonction PURE.

    Pourquoi : le P&L vs prix d'entrée ne voit pas qu'une position passée
    de +30% à +12% vient de rendre 60% de ses gains. Le trailing stop
    compare au sommet, pas à l'entrée.

    Limite assumée : l'historique du snapshot est tronqué (~45 séances) —
    pour une position plus ancienne, le plus haut est celui de la fenêtre
    disponible. C'est le trailing RÉCENT, le plus pertinent pour agir.

    Retourne (hwm, drawdown_pct) ou (None, None) si incalculable.
    """
    try:
        if hist is None or hist.empty or not lots or not prix:
            return None, None
        # Date du premier lot encore ouvert (achat ou import — pas les ventes)
        dates_achat = [l.get("date_achat") for l in lots
                       if l.get("type") in (None, "achat", "import") and l.get("date_achat")]
        if not dates_achat:
            return None, None
        depuis = pd.Timestamp(min(dates_achat))

        close  = hist["Close"]
        idx    = close.index
        # Index tz-aware (yfinance) vs date naïve → normalise avant comparaison
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        fenetre = close[idx >= depuis]
        if fenetre.empty:
            fenetre = close          # position plus ancienne que la fenêtre

        hwm = float(max(fenetre.max(), prix))   # le prix live peut être le sommet
        if hwm <= 0:
            return None, None
        dd = round((prix - hwm) / hwm * 100, 2)
        return round(hwm, 4), dd
    except Exception:
        return None, None
