# alerts/mailer.py
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from config               import (
    SMTP_HOST, SMTP_PORT,
    SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM,
)


def send_alert(to_email: str, username: str,
               ticker: str, company: str,
               old_reco: str, new_reco: str,
               score: float, prix: float,
               variation: float,
               reco_changed: bool = False,
               var_triggered: bool = False,
               context: str = ""):

    icons  = {"ACHETER": "▲", "VENDRE": "▼", "NEUTRE": "◆"}
    colors = {"ACHETER": "#1D9E75", "VENDRE": "#D85A30", "NEUTRE": "#BA7517"}
    icon   = icons.get(new_reco, "•")
    color  = colors.get(new_reco, "#374151")
    var_color = "#1D9E75" if variation >= 0 else "#D85A30"

    # ── Sujet ─────────────────────────────────────────────────
    if reco_changed and var_triggered:
        subject = f"[StockDecisionEngine] {icon} {ticker} — Reco + Variation ({variation:+.1f}%)"
    elif reco_changed:
        subject = f"[StockDecisionEngine] {icon} {ticker} — Changement de recommandation"
    else:
        subject = f"[StockDecisionEngine] {ticker} — Variation significative ({variation:+.1f}%)"

    # ── Bandeaux déclencheurs ─────────────────────────────────
    trigger_blocks = ""

    if var_triggered:
        trigger_blocks += f"""
      <div style="background:#FFF3CD;border-left:4px solid #F59E0B;
                  padding:10px 14px;border-radius:4px;margin-bottom:10px">
        <span style="font-size:13px;font-weight:600;color:#92400E">
          ⚠️ Variation significative
        </span>
        <span style="font-size:20px;font-weight:700;color:{var_color};
                     margin-left:12px">
          {variation:+.2f}%
        </span>
      </div>"""

    if reco_changed:
        trigger_blocks += f"""
      <div style="background:#EEF2FF;border-left:4px solid #6366F1;
                  padding:10px 14px;border-radius:4px;margin-bottom:10px">
        <span style="font-size:13px;font-weight:600;color:#3730A3">
          🔔 Changement de recommandation
        </span>
        <span style="font-size:15px;color:#6b7280;
                     text-decoration:line-through;margin-left:12px">
          {old_reco}
        </span>
        <span style="font-size:15px;color:#374151;margin:0 6px">→</span>
        <span style="font-size:16px;font-weight:700;color:{color}">
          {icon} {new_reco}
        </span>
      </div>"""

    # ── Ligne recommandation dans le tableau ──────────────────
    # Affichée seulement si la reco N'a PAS changé (simple info)
    # ou si elle a changé (déjà dans le bandeau, on la répète sobrement)
    if reco_changed:
        reco_row = ""   # déjà affiché dans le bandeau, inutile de doubler
    else:
        reco_row = f"""
        <tr>
          <td style="padding:8px;background:#f8f9fa;color:#6b7280;font-size:13px">
            Recommandation
          </td>
          <td style="padding:8px;background:#f8f9fa;font-weight:500;
                     font-size:15px;color:{color}">
            {icon} {new_reco}
          </td>
        </tr>"""

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;
                margin:0 auto;padding:20px">

      <div style="border-left:4px solid {color};padding-left:16px;
                  margin-bottom:16px">
        <h2 style="margin:0 0 4px;color:#111827">{ticker} — {company}</h2>
        <p style="margin:0;color:#6b7280;font-size:13px">
          Alerte StockDecisionEngine pour {username}
        </p>
      </div>

      {trigger_blocks}

      <table style="width:100%;border-collapse:collapse;margin-top:12px;
                    margin-bottom:20px">
        <tr>
          <td style="padding:8px;background:#f8f9fa;color:#6b7280;font-size:13px">
            Cours actuel
          </td>
          <td style="padding:8px;background:#f8f9fa;font-weight:500;font-size:15px">
            ${prix:.2f}
            <span style="color:{var_color};font-size:13px">
              ({variation:+.2f}%)
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:8px;color:#6b7280;font-size:13px">Score global</td>
          <td style="padding:8px;font-weight:500;font-size:15px;color:{color}">
            {score:.1f} / 100
          </td>
        </tr>
        {reco_row}
      </table>

      {f'''<div style="background:{'#EAF3DE' if variation >= 0 else '#FFF3CD'};
                  border-left:4px solid {'#1D9E75' if variation >= 0 else '#F59E0B'};
                  border-radius:6px;padding:12px 14px;margin-bottom:16px;
                  font-size:13px;color:#374151;line-height:1.6">
        <span style="font-size:11px;font-weight:600;
                     color:{'#27500A' if variation >= 0 else '#92400E'};
                     text-transform:uppercase;letter-spacing:0.05em">
          Analyse IA
        </span><br><br>
        {context}
      </div>''' if context else ''}

      <p style="color:#9ca3af;font-size:11px;
                border-top:1px solid #e5e7eb;padding-top:12px">
        Cet email a été envoyé automatiquement par StockDecisionEngine.
        Outil éducatif — pas un conseil financier.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"]          = subject
    msg["From"]             = SMTP_FROM
    msg["To"]               = to_email
    msg["X-Priority"]       = "1"
    msg["X-MSMail-Priority"]= "High"
    msg["Importance"]       = "High"
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(SMTP_FROM, to_email, msg.as_string())
