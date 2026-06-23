# ui/charts.py — graphiques matplotlib + plotly pour Streamlit
# Alimentés directement par le DataFrame Pandas enrichi.

import matplotlib.pyplot   as plt
import matplotlib.dates    as mdates
import matplotlib.gridspec as gridspec
import pandas              as pd
import numpy               as np
import plotly.graph_objects as go

plt.style.use("seaborn-v0_8-whitegrid")

plt.rcParams.update({
    "font.size":         9,
    "axes.titlesize":    11,
    "axes.titleweight":  "bold",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "legend.framealpha": 0.8,
    "legend.edgecolor":  "#cccccc",
    "figure.dpi":        120,
})

def plot_price(hist: pd.DataFrame, ticker: str):
    """Cours 30j + volume. hist = DataFrame Pandas enrichi."""
    df    = hist.tail(30)
    close = df["Close"]
    color = "#00e57a" if close.iloc[-1] >= close.iloc[0] else "#ff3d5a"

    fig = plt.figure(figsize=(11, 6))
    gs  = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.04)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)

    # Cours — Series Pandas passée directement à matplotlib
    ax1.plot(close.index, close, color=color, lw=2, zorder=3)
    ax1.fill_between(close.index, close, close.min(), color=color, alpha=0.07)
    ax1.plot(df.index, df["MA20"], color="#f5c842", lw=1.2, ls="--", label="MA20", alpha=0.9)
    ax1.plot(df.index, df["MA50"], color="#4da6ff", lw=1.2, ls="--", label="MA50", alpha=0.9)
    ax1.fill_between(df.index, df["BB_upper"], df["BB_lower"], color="#4da6ff", alpha=0.04)
    ax1.set_title(f"{ticker} — 30 jours", pad=8)
    ax1.legend(fontsize=8); ax1.grid(True, alpha=0.35)
    plt.setp(ax1.get_xticklabels(), visible=False)

    # Volume coloré via .map() Pandas (vectorisé)
    vol_col = (df["Close"] >= df["Open"]).map({True: "#00e57a", False: "#ff3d5a"})
    ax2.bar(df.index, df["Volume"], color=vol_col.values, alpha=0.6, width=0.8)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"{x/1e6:.0f}M"))
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate(rotation=30)
    plt.tight_layout(); return fig

def plot_rsi(hist: pd.DataFrame):
    """RSI 14j avec zones colorées depuis pd.Series."""
    df = hist.tail(30)["RSI"]
    v  = df.iloc[-1]
    c  = "#ff3d5a" if v > 70 else "#00e57a" if v < 30 else "#f5c842"
    fig, ax = plt.subplots(figsize=(11, 3))
    ax.plot(df.index, df, color="#4da6ff", lw=2)
    ax.axhline(70, color="#ff3d5a", ls="--", lw=1, alpha=0.8, label="Surachat 70")
    ax.axhline(30, color="#00e57a", ls="--", lw=1, alpha=0.8, label="Survente 30")
    ax.fill_between(df.index, 70, 100, color="#ff3d5a", alpha=0.06)
    ax.fill_between(df.index, 0,  30,  color="#00e57a", alpha=0.06)
    ax.scatter([df.index[-1]], [v], color=c, s=60, zorder=5)
    ax.annotate(f"RSI={v:.1f}", (df.index[-1],v), xytext=(-55,8),
                textcoords="offset points", color=c, fontsize=9, fontweight="bold")
    ax.set_ylim(0,100); ax.legend(fontsize=8); ax.grid(True,alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate(rotation=30); plt.tight_layout(); return fig

def plot_macd(hist: pd.DataFrame):
    """MACD avec histogramme vert/rouge via pd.Series.where()."""
    df = hist.tail(30)
    fig, ax = plt.subplots(figsize=(11, 3))
    ax.plot(df.index, df["MACD"],     color="#4da6ff", lw=1.5, label="MACD")
    ax.plot(df.index, df["MACD_sig"], color="#f5c842", lw=1.5, label="Signal")
    pos = df["MACD_hist"].where(df["MACD_hist"] >= 0).fillna(0)
    neg = df["MACD_hist"].where(df["MACD_hist"]  < 0).fillna(0)
    ax.bar(df.index, pos, color="#00e57a", alpha=0.5, width=0.8)
    ax.bar(df.index, neg, color="#ff3d5a", alpha=0.5, width=0.8)
    ax.axhline(0, color="#5a6a7a", lw=1, alpha=0.5)
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate(rotation=30); plt.tight_layout(); return fig


def plot_candlestick(hist: pd.DataFrame, ticker: str) -> go.Figure:
    """Chandeliers japonais (Plotly) avec MA20/MA50 et figures chartistes annotées."""
    from analysis.candle_patterns import detect_patterns

    df       = hist.tail(60).copy()
    patterns = detect_patterns(df)

    fig = go.Figure()

    # Chandeliers
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing_line_color="#00e57a",
        decreasing_line_color="#ff3d5a",
        name="OHLC",
    ))

    # MA20 et MA50 en overlay
    if df["MA20"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MA20"],
            line=dict(color="#f5c842", width=1.5, dash="dash"),
            name="MA20",
        ))
    if df["MA50"].notna().any():
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MA50"],
            line=dict(color="#4da6ff", width=1.5, dash="dash"),
            name="MA50",
        ))

    # ── Marqueurs de figures chartistes ──────────────────
    if not patterns.empty:
        bull = patterns[patterns["signal"] == "bullish"]
        bear = patterns[patterns["signal"] == "bearish"]
        neut = patterns[patterns["signal"] == "neutre"]

        def _price_at(dates, col):
            return df.loc[df.index.isin(dates), col]

        if not bull.empty:
            fig.add_trace(go.Scatter(
                x=bull["date"],
                y=_price_at(bull["date"], "Low") * 0.995,
                mode="markers+text",
                marker=dict(symbol="triangle-up", size=14, color="#00e57a"),
                text=bull["pattern"],
                textposition="bottom center",
                textfont=dict(size=9, color="#00e57a"),
                hovertext=bull["pattern"] + " — " + bull["description"],
                hoverinfo="text",
                name="Signal haussier",
            ))

        if not bear.empty:
            fig.add_trace(go.Scatter(
                x=bear["date"],
                y=_price_at(bear["date"], "High") * 1.005,
                mode="markers+text",
                marker=dict(symbol="triangle-down", size=14, color="#ff3d5a"),
                text=bear["pattern"],
                textposition="top center",
                textfont=dict(size=9, color="#ff3d5a"),
                hovertext=bear["pattern"] + " — " + bear["description"],
                hoverinfo="text",
                name="Signal baissier",
            ))

        if not neut.empty:
            fig.add_trace(go.Scatter(
                x=neut["date"],
                y=_price_at(neut["date"], "High") * 1.005,
                mode="markers+text",
                marker=dict(symbol="diamond", size=10, color="#f5c842"),
                text=neut["pattern"],
                textposition="top center",
                textfont=dict(size=9, color="#f5c842"),
                hovertext=neut["pattern"] + " — " + neut["description"],
                hoverinfo="text",
                name="Neutre",
            ))

    fig.update_layout(
        title=f"{ticker} — Chandeliers 60 jours",
        xaxis_rangeslider_visible=False,
        xaxis_title=None,
        yaxis_title="Prix",
        template="plotly_dark",
        height=460,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.06, x=0),
    )
    return fig
