# flask_app/charts_helpers.py — convertit les figures en formats web
# matplotlib → base64 PNG (data URI)
# plotly → JSON string (Plotly.newPlot côté JS)

import io
import base64
import matplotlib
matplotlib.use("Agg")  # mode sans interface graphique


def fig_to_b64(fig) -> str:
    """Convertit une figure matplotlib en data URI base64."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    buf.seek(0)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()


def plotly_to_json(fig) -> str:
    """Sérialise une figure Plotly en JSON pour Plotly.newPlot()."""
    return fig.to_json()


def build_charts(hist, ticker: str) -> dict:
    """
    Génère les 3 graphiques et retourne un dict prêt pour le template.
    Retourne {} en cas d'erreur globale, None par graphique si erreur partielle.
    """
    charts = {}
    try:
        from ui.charts import plot_price
        charts["price_b64"] = fig_to_b64(plot_price(hist, ticker))
    except Exception:
        charts["price_b64"] = None

    try:
        from ui.charts import plot_rsi
        charts["rsi_b64"] = fig_to_b64(plot_rsi(hist))
    except Exception:
        charts["rsi_b64"] = None

    try:
        from ui.charts import plot_candlestick
        charts["candle_json"] = plotly_to_json(plot_candlestick(hist, ticker))
    except Exception:
        charts["candle_json"] = None

    return charts
