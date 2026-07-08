# analysis/backtest.py — rejeu historique du score technique SDE
#
# Principe : on fait "remonter le temps" au moteur de scoring. Pour chaque
# journée de bourse des 2 dernières années, on recalcule le score technique
# comme si on était ce jour-là, puis on regarde ce que le cours a réellement
# fait 5 et 20 jours plus tard. On mesure ainsi la fiabilité passée des
# signaux ACHETER / VENDRE.
#
# Pourquoi c'est possible sans biais de look-ahead (= tricher en utilisant
# une info future) : tous nos indicateurs (RSI, MACD, MA, Bollinger) sont
# calculés avec .ewm() et .rolling() Pandas, qui ne regardent QUE le passé.
# La valeur du RSI au 3 mars ne dépend que des cours d'avant le 3 mars.
# On peut donc enrichir le DataFrame UNE seule fois, puis lire ligne à ligne.
#
# Limite assumée : on ne rejoue que le score TECHNIQUE. Les scores
# fondamental et médiatique exigeraient des archives de news et de bilans
# datées, qu'on n'a pas. L'UI l'affiche clairement.

import time
import numpy as np
import pandas as pd

from analysis.scoring   import score_technique, TECH_WEIGHTS, TECH_LABELS
from utils.indicators   import add_indicators
from config             import SCORE_BUY, SCORE_SELL

# Période minimale de chauffe : MA50 a besoin de 50 points pour exister.
# Avant ça, les signaux seraient calculés sur des NaN → on les saute.
WARMUP_DAYS = 50

# Cache en mémoire {ticker: (timestamp, résultat)} — un backtest 2 ans
# télécharge ~500 bougies et boucle 450 fois : inutile de le refaire
# à chaque clic. TTL 1 h (les données quotidiennes ne bougent pas plus vite).
_CACHE: dict = {}
_CACHE_TTL_S = 3600


def _fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Télécharge l'OHLCV quotidien (2 ans par défaut).
    Même stratégie que data/market.py : yfinance d'abord (gratuit, illimité
    en local), puis Twelve Data en secours — yfinance est rate-limité
    sur Render et échoue systématiquement en production.
    """
    hist = pd.DataFrame()
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period)
    except Exception as e:
        print(f"[Backtest] yfinance erreur ({ticker}) : {e}", flush=True)

    if hist is None or hist.empty:
        # Fallback cloud : on réutilise la fonction de market.py telle quelle.
        # Attention : outputsize de Twelve Data compte des jours de BOURSE
        # (pas calendaires) — 2 ans ≈ 504 séances (252/an).
        from data.market import _get_candles_td
        print(f"[Backtest] fallback Twelve Data pour {ticker}", flush=True)
        hist = _get_candles_td(ticker, 504)

    if hist is None or hist.empty:
        raise ValueError(f"Aucune donnée historique pour {ticker}")

    # Normalise l'index en dates simples : yfinance renvoie des Timestamps
    # avec fuseau horaire (source de bugs de comparaison), Twelve Data non —
    # d'où le test avant le tz_localize (qui planterait sur un index naïf).
    if getattr(hist.index, "tz", None) is not None:
        hist.index = hist.index.tz_localize(None)
    hist.index = hist.index.normalize()
    return hist


def _enrich(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute tous les indicateurs attendus par compute_tech_signals().
    Reproduit ce que fait data/market.py sur les données live :
    add_indicators() + Ret_5d + Vol_ratio.
    """
    h = hist.pipe(add_indicators)          # .pipe() = chaînage lisible
    c = h["Close"]
    h["Ret_5d"]    = (c.pct_change(5) * 100).round(2)
    h["Vol_ratio"] = (h["Volume"] / h["Volume"].rolling(20).mean()).round(2)
    return h


def _reco_technique(score: float) -> str:
    """Convertit le score technique seul en signal, mêmes seuils que scoring.py."""
    if   score > SCORE_BUY:  return "ACHETER"
    elif score < SCORE_SELL: return "VENDRE"
    else:                    return "NEUTRE"


def _replay_scores(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Boucle jour par jour : à chaque date T on passe à score_technique()
    le DataFrame tronqué à T (hist.iloc[:i+1]) — exactement ce que voit
    le moteur en production. On réutilise score_technique() tel quel
    plutôt que de dupliquer ses poids : si les poids changent un jour,
    le backtest reste automatiquement fidèle.
    """
    rows = []
    for i in range(WARMUP_DAYS, len(hist)):
        vue_du_jour = hist.iloc[: i + 1]          # tout ce qu'on savait à T
        res = score_technique({"history": vue_du_jour})
        rows.append({
            "date":  hist.index[i],
            "close": float(hist["Close"].iloc[i]),
            "score": res["score"],
            "reco":  _reco_technique(res["score"]),
            # Codes des signaux actifs ce jour-là (ex. {"ma_cross_up", ...})
            # → matière première de l'attribution par signal.
            # Un set : les tests d'appartenance ("code in ...") sont O(1).
            "signaux": {s["code"] for s in res["signals"]},
        })
    # DataFrame indexé par date → facilite les .shift() qui suivent
    return pd.DataFrame(rows).set_index("date")


def _stats_par_action(bt: pd.DataFrame, horizons: tuple) -> dict:
    """
    Pour chaque horizon (ex. 5 et 20 jours), calcule par type de signal :
      - n         : nombre de signaux émis
      - hit_pct   : % de signaux "gagnants" (hausse après ACHETER,
                    baisse après VENDRE)
      - ret_moyen : variation moyenne du cours après le signal (%)
    """
    out = {}
    for h in horizons:
        # .shift(-h) décale la colonne vers le HAUT : sur la ligne du jour T,
        # on lit le cours de T+h. C'est le seul endroit où on regarde le
        # futur — et c'est voulu : on évalue le signal a posteriori.
        fwd = (bt["close"].shift(-h) / bt["close"] - 1) * 100
        stats_h = {}
        for action in ("ACHETER", "VENDRE", "NEUTRE"):
            mask = (bt["reco"] == action) & fwd.notna()
            n = int(mask.sum())
            if n == 0:
                stats_h[action] = {"n": 0, "hit_pct": None, "ret_moyen": None}
                continue
            rets = fwd[mask]
            # Un signal ACHETER est "bon" si le cours monte ensuite,
            # un VENDRE s'il baisse. NEUTRE n'a pas de notion de réussite.
            if action == "ACHETER":
                hits = (rets > 0).mean() * 100
            elif action == "VENDRE":
                hits = (rets < 0).mean() * 100
            else:
                hits = None
            stats_h[action] = {
                "n":         n,
                "hit_pct":   round(float(hits), 1) if hits is not None else None,
                "ret_moyen": round(float(rets.mean()), 2),
            }
        out[str(h)] = stats_h
    return out


def _attribution_par_signal(bt: pd.DataFrame, horizon: int = 20) -> list:
    """
    Fiabilité historique de CHAQUE signal technique sur ce ticker.

    Piège statistique évité ici : un signal comme "MA20 > MA50" reste vrai
    des semaines d'affilée. Compter chaque jour comme une observation
    gonflerait artificiellement l'échantillon (450 jours ≈ parfois 20
    vrais événements). On raisonne donc en ÉPISODES : une période continue
    d'activation = 1 observation, mesurée à son PREMIER jour (le moment où
    un investisseur aurait réagi au signal).

    Un signal est "réussi" si le cours a bougé dans SON sens à l'horizon :
    hausse pour un signal à poids positif, baisse pour un poids négatif.
    """
    fwd = (bt["close"].shift(-horizon) / bt["close"] - 1) * 100

    out = []
    for code in TECH_WEIGHTS.index:
        # pd.Series booléenne : le signal était-il actif ce jour-là ?
        actif = bt["signaux"].apply(lambda s: code in s)

        # Début d'épisode = actif aujourd'hui MAIS PAS hier.
        # .shift(1) décale d'un jour ; fill_value=False traite le 1er jour.
        debuts = actif & ~actif.shift(1, fill_value=False)

        # On ne mesure que les débuts dont l'horizon est observable
        rets = fwd[debuts & fwd.notna()]
        if rets.empty:
            continue

        points = int(TECH_WEIGHTS[code])
        # Réussite = le marché a suivi le sens annoncé par le signal
        hits = (rets > 0) if points > 0 else (rets < 0)

        out.append({
            "code":       code,
            "label":      TECH_LABELS.get(code, code),
            "points":     points,
            "sens":       "haussier" if points > 0 else "baissier",
            "n_jours":    int(actif.sum()),      # jours d'activation (info)
            "n_episodes": int(len(rets)),        # vraies observations
            "hit_pct":    round(float(hits.mean() * 100), 1),
            "ret_moyen":  round(float(rets.mean()), 2),
        })

    # Les moins fiables d'abord — c'est eux qu'on cherche à identifier
    return sorted(out, key=lambda s: s["hit_pct"])


def _equity_curve(bt: pd.DataFrame) -> dict:
    """
    Simulation vectorisée : on est investi ("long") uniquement les jours
    où le signal de la VEILLE était ACHETER, en cash sinon.

    Le .shift(1) sur la position est crucial : le signal calculé à la
    clôture de T ne peut être exécuté qu'à partir de T+1. Sans ce décalage,
    on s'achèterait soi-même dans le passé (biais classique de backtest).
    """
    ret_1j   = bt["close"].pct_change()                       # rendement quotidien
    position = (bt["reco"] == "ACHETER").astype(int).shift(1) # 1 = investi, 0 = cash
    strat    = (1 + ret_1j * position.fillna(0)).cumprod() * 100   # base 100
    bh       = (1 + ret_1j.fillna(0)).cumprod() * 100              # buy & hold

    return {
        "dates":     [d.strftime("%Y-%m-%d") for d in bt.index],
        "strategie": [round(float(v), 2) for v in strat.fillna(100)],
        "buy_hold":  [round(float(v), 2) for v in bh],
        "strat_pct": round(float(strat.iloc[-1] - 100), 1),
        "bh_pct":    round(float(bh.iloc[-1] - 100), 1),
    }


def run_backtest(ticker: str, period: str = "2y",
                 horizons: tuple = (5, 20), use_cache: bool = True) -> dict:
    """
    Point d'entrée du backtest — appelé par la route Flask.
    Retourne un dict prêt à sérialiser en JSON.
    """
    ticker = ticker.upper().strip()

    # Cache mémoire : évite de refaire 450 calculs de score par clic
    if use_cache and ticker in _CACHE:
        ts, cached = _CACHE[ticker]
        if time.time() - ts < _CACHE_TTL_S:
            return cached

    hist = _enrich(_fetch_history(ticker, period))
    if len(hist) <= WARMUP_DAYS + 25:
        raise ValueError(
            f"Historique trop court ({len(hist)} jours) — "
            f"il faut au moins {WARMUP_DAYS + 25} jours de cotation."
        )

    bt     = _replay_scores(hist)
    stats  = _stats_par_action(bt, horizons)
    curve  = _equity_curve(bt)
    attrib = _attribution_par_signal(bt, horizon=20)

    # Répartition des signaux (pour l'affichage "X j ACHETER / Y j NEUTRE…")
    repartition = bt["reco"].value_counts().to_dict()

    result = {
        "ok":          True,
        "ticker":      ticker,
        "date_debut":  bt.index[0].strftime("%Y-%m-%d"),
        "date_fin":    bt.index[-1].strftime("%Y-%m-%d"),
        "n_jours":     len(bt),
        "repartition": {k: int(v) for k, v in repartition.items()},
        "stats":       stats,
        "curve":       curve,
        "attribution": attrib,
        # Rappel de la limite méthodologique, affiché tel quel dans l'UI
        "note": ("Backtest du score technique uniquement — les scores "
                 "fondamental et médiatique ne sont pas reconstituables "
                 "dans le passé (pas d'archives de news datées)."),
    }
    _CACHE[ticker] = (time.time(), result)
    return result
