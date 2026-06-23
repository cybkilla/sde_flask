# analysis/candle_patterns.py — Détection de figures chartistes en Pandas pur
import pandas as pd


def detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyse le DataFrame OHLCV et retourne un DataFrame des figures détectées.
    Colonnes résultat : date, pattern, signal (bullish/bearish), description
    """
    o = df["Open"]
    h = df["High"]
    l = df["Low"]
    c = df["Close"]

    body      = (c - o).abs()                  # taille du corps
    candle    = (h - l).replace(0, 1e-9)       # taille totale (évite /0)
    upper_sh  = h - c.where(c > o, o)          # ombre haute
    lower_sh  = c.where(c < o, o) - l          # ombre basse
    body_ratio = body / candle                  # rapport corps/chandelier
    is_bull   = c > o                          # bougie verte
    is_bear   = c < o                          # bougie rouge

    results = []

    for i in range(2, len(df)):
        idx  = df.index[i]
        idx1 = df.index[i - 1]
        idx2 = df.index[i - 2]

        # ── Patterns 1 bougie ─────────────────────────────

        # Doji — corps très petit, indécision
        if body_ratio.iloc[i] < 0.08:
            results.append({
                "date": idx, "pattern": "Doji",
                "signal": "neutre",
                "description": "Indécision — corps quasi inexistant"
            })
            continue

        # Marteau (Hammer) — bas d'une baisse, ombre basse longue → retournement haussier
        if (body_ratio.iloc[i] < 0.35
                and lower_sh.iloc[i] > 2 * body.iloc[i]
                and upper_sh.iloc[i] < body.iloc[i] * 0.5
                and is_bull.iloc[i]):
            results.append({
                "date": idx, "pattern": "Marteau",
                "signal": "bullish",
                "description": "Retournement haussier probable — ombre basse longue"
            })
            continue

        # Étoile filante (Shooting Star) — ombre haute longue → retournement baissier
        if (body_ratio.iloc[i] < 0.35
                and upper_sh.iloc[i] > 2 * body.iloc[i]
                and lower_sh.iloc[i] < body.iloc[i] * 0.5
                and is_bear.iloc[i]):
            results.append({
                "date": idx, "pattern": "Étoile filante",
                "signal": "bearish",
                "description": "Retournement baissier probable — ombre haute longue"
            })
            continue

        # Marteau inversé — ombre haute longue, bougie haussière
        if (body_ratio.iloc[i] < 0.35
                and upper_sh.iloc[i] > 2 * body.iloc[i]
                and lower_sh.iloc[i] < body.iloc[i] * 0.5
                and is_bull.iloc[i]):
            results.append({
                "date": idx, "pattern": "Marteau inversé",
                "signal": "bullish",
                "description": "Possible retournement haussier après baisse"
            })
            continue

        # Marubozu haussier — corps occupe quasi toute la bougie
        if body_ratio.iloc[i] > 0.90 and is_bull.iloc[i]:
            results.append({
                "date": idx, "pattern": "Marubozu haussier",
                "signal": "bullish",
                "description": "Force acheteuse dominante — pas d'ombres"
            })
            continue

        # Marubozu baissier
        if body_ratio.iloc[i] > 0.90 and is_bear.iloc[i]:
            results.append({
                "date": idx, "pattern": "Marubozu baissier",
                "signal": "bearish",
                "description": "Force vendeuse dominante — pas d'ombres"
            })
            continue

        # ── Patterns 2 bougies ────────────────────────────

        # Avalement haussier (Bullish Engulfing)
        if (is_bear.iloc[i - 1]
                and is_bull.iloc[i]
                and o.iloc[i] < c.iloc[i - 1]
                and c.iloc[i] > o.iloc[i - 1]):
            results.append({
                "date": idx, "pattern": "Avalement haussier",
                "signal": "bullish",
                "description": "Grande bougie verte englobe la rouge précédente"
            })
            continue

        # Avalement baissier (Bearish Engulfing)
        if (is_bull.iloc[i - 1]
                and is_bear.iloc[i]
                and o.iloc[i] > c.iloc[i - 1]
                and c.iloc[i] < o.iloc[i - 1]):
            results.append({
                "date": idx, "pattern": "Avalement baissier",
                "signal": "bearish",
                "description": "Grande bougie rouge englobe la verte précédente"
            })
            continue

        # Harcèlement haussier (Piercing Line)
        if (is_bear.iloc[i - 1]
                and is_bull.iloc[i]
                and o.iloc[i] < l.iloc[i - 1]
                and c.iloc[i] > (o.iloc[i - 1] + c.iloc[i - 1]) / 2):
            results.append({
                "date": idx, "pattern": "Ligne de pénétration",
                "signal": "bullish",
                "description": "Bougie verte clôture au-dessus du milieu de la rouge"
            })
            continue

        # ── Patterns 3 bougies ────────────────────────────

        # Étoile du matin (Morning Star) — retournement haussier
        if (is_bear.iloc[i - 2]
                and body_ratio.iloc[i - 1] < 0.30
                and is_bull.iloc[i]
                and c.iloc[i] > (o.iloc[i - 2] + c.iloc[i - 2]) / 2):
            results.append({
                "date": idx, "pattern": "Étoile du matin",
                "signal": "bullish",
                "description": "Retournement haussier fort — 3 bougies (rouge, doji, verte)"
            })
            continue

        # Étoile du soir (Evening Star) — retournement baissier
        if (is_bull.iloc[i - 2]
                and body_ratio.iloc[i - 1] < 0.30
                and is_bear.iloc[i]
                and c.iloc[i] < (o.iloc[i - 2] + c.iloc[i - 2]) / 2):
            results.append({
                "date": idx, "pattern": "Étoile du soir",
                "signal": "bearish",
                "description": "Retournement baissier fort — 3 bougies (verte, doji, rouge)"
            })
            continue

        # Trois soldats blancs (Three White Soldiers)
        if (is_bull.iloc[i - 2] and is_bull.iloc[i - 1] and is_bull.iloc[i]
                and c.iloc[i] > c.iloc[i - 1] > c.iloc[i - 2]
                and body_ratio.iloc[i] > 0.5
                and body_ratio.iloc[i - 1] > 0.5):
            results.append({
                "date": idx, "pattern": "3 soldats blancs",
                "signal": "bullish",
                "description": "3 bougies vertes consécutives — tendance haussière forte"
            })
            continue

        # Trois corbeaux noirs (Three Black Crows)
        if (is_bear.iloc[i - 2] and is_bear.iloc[i - 1] and is_bear.iloc[i]
                and c.iloc[i] < c.iloc[i - 1] < c.iloc[i - 2]
                and body_ratio.iloc[i] > 0.5
                and body_ratio.iloc[i - 1] > 0.5):
            results.append({
                "date": idx, "pattern": "3 corbeaux noirs",
                "signal": "bearish",
                "description": "3 bougies rouges consécutives — tendance baissière forte"
            })

    return pd.DataFrame(results) if results else pd.DataFrame(
        columns=["date", "pattern", "signal", "description"]
    )
