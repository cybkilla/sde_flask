# alerts/mailer.py — envoi d'emails via Resend (HTTP, port 443 — fonctionne sur Render)
import os
import resend


SDE_BASE_URL = "https://sde-flask.onrender.com"


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

    if reco_changed:
        reco_row = ""
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

      <div style="border-top:1px solid #e5e7eb;padding-top:12px;margin-top:4px">
        <a href="{SDE_BASE_URL}/analyze/{ticker}"
           style="display:inline-block;background:#1D9E75;color:#fff;
                  font-size:13px;font-weight:600;text-decoration:none;
                  padding:8px 18px;border-radius:6px;margin-bottom:10px">
          Voir l'analyse complète de {ticker} →
        </a>
        <p style="color:#9ca3af;font-size:11px;margin:0">
          Cet email a été envoyé automatiquement par StockDecisionEngine.
          Outil éducatif — pas un conseil financier.
        </p>
      </div>
    </div>
    """

    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")

    if not api_key:
        print(f"[Mailer] RESEND_API_KEY manquante — email non envoyé à {to_email}", flush=True)
        return

    resend.api_key = api_key
    resend.Emails.send({
        "from":    from_addr,
        "to":      [to_email],
        "subject": subject,
        "html":    body,
    })
    print(f"[Mailer] Email envoyé à {to_email} ({ticker})", flush=True)


def send_tp_sl_alert(to_email: str, username: str,
                     ticker: str, company: str,
                     level_type: str,   # "take_profit" | "stop_loss"
                     prix_live: float, prix_cible: float):
    """Envoie une alerte Take Profit ou Stop Loss."""
    is_tp     = level_type == "take_profit"
    color     = "#1D9E75" if is_tp else "#D85A30"
    icon      = "🎯" if is_tp else "🛡️"
    label     = "Take Profit atteint" if is_tp else "Stop Loss atteint"
    variation = round((prix_live - prix_cible) / prix_cible * 100, 2)
    var_str   = f"{variation:+.2f}%"

    subject = f"[StockDecisionEngine] {icon} {ticker} — {label} ({var_str})"

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px">
      <div style="border-left:4px solid {color};padding-left:16px;margin-bottom:16px">
        <h2 style="margin:0 0 4px;color:#111827">{ticker} — {company}</h2>
        <p style="margin:0;color:#6b7280;font-size:13px">
          Alerte StockDecisionEngine pour {username}
        </p>
      </div>

      <div style="background:{'#EAF3DE' if is_tp else '#FAECE7'};
                  border-left:4px solid {color};border-radius:6px;
                  padding:14px 16px;margin-bottom:16px">
        <div style="font-size:20px;font-weight:700;color:{color};margin-bottom:6px">
          {icon} {label}
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <tr>
            <td style="padding:4px 0;color:#6b7280">Cours actuel</td>
            <td style="padding:4px 0;font-weight:700;color:{color}">${prix_live:.4f}</td>
          </tr>
          <tr>
            <td style="padding:4px 0;color:#6b7280">Niveau {'TP' if is_tp else 'SL'} défini</td>
            <td style="padding:4px 0;font-weight:600">${prix_cible:.4f}</td>
          </tr>
          <tr>
            <td style="padding:4px 0;color:#6b7280">Écart</td>
            <td style="padding:4px 0;font-weight:600;color:{color}">{var_str}</td>
          </tr>
        </table>
      </div>

      <p style="font-size:13px;color:#374151;line-height:1.6">
        {"Félicitations — votre objectif de prise de bénéfices a été atteint. Pensez à réévaluer votre position." if is_tp
          else "Votre seuil de protection a été franchi. Une revue de votre position est recommandée."}
      </p>

      <div style="border-top:1px solid #e5e7eb;padding-top:12px;margin-top:8px">
        <a href="{SDE_BASE_URL}/analyze/{ticker}"
           style="display:inline-block;background:{color};color:#fff;
                  font-size:13px;font-weight:600;text-decoration:none;
                  padding:8px 18px;border-radius:6px;margin-bottom:10px">
          Voir l'analyse de {ticker} →
        </a>
        <p style="color:#9ca3af;font-size:11px;margin:0">
          Cet email a été envoyé automatiquement par StockDecisionEngine.
          Outil éducatif — pas un conseil financier.
        </p>
      </div>
    </div>
    """

    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")

    if not api_key:
        print(f"[Mailer] RESEND_API_KEY manquante — TP/SL email non envoyé", flush=True)
        return

    resend.api_key = api_key
    resend.Emails.send({
        "from":    from_addr,
        "to":      [to_email],
        "subject": subject,
        "html":    body,
    })
    print(f"[Mailer] TP/SL email envoyé à {to_email} ({ticker} {label})", flush=True)
    print(f"[Mailer] Email envoyé à {to_email} ({ticker})", flush=True)


def send_advice_change_alert(to_email: str, username: str,
                             ticker: str, company: str,
                             old_action: str, new_action: str,
                             advice: dict, prix: float):
    """
    Email envoyé quand le CONSEIL POSITION du jour change d'action par
    rapport au précédent (ex. TENIR → ALLÉGER). Distinct de send_alert()
    (recommandation globale ACHETER/VENDRE/NEUTRE) : ici c'est le conseil
    personnalisé, calculé sur la position réelle de l'utilisateur.
    Anti-doublon par construction : appelé uniquement à la CRÉATION du
    conseil du jour (une fois par jour et par ticker maximum).
    """
    # Couleurs alignées sur ACTION_LABELS de l'advisor
    colors = {"ACHETER": "#1D9E75", "RENFORCER": "#15803d", "TENIR": "#BA7517",
              "SURVEILLER": "#5a6a7a", "ALLÉGER": "#D85A30", "VENDRE": "#991b1b"}
    icons  = {"ACHETER": "↑", "RENFORCER": "↗", "TENIR": "◆",
              "SURVEILLER": "◎", "ALLÉGER": "↘", "VENDRE": "↓"}
    color  = colors.get(new_action, "#374151")
    icon   = icons.get(new_action, "•")

    subject = (f"[StockDecisionEngine] {icon} {ticker} — "
               f"Conseil position : {old_action} → {new_action}")

    qte = advice.get("quantite_suggeree")
    qte_html = (f'<tr><td style="padding:8px;color:#6b7280;font-size:13px">'
                f'Quantité suggérée</td>'
                f'<td style="padding:8px;font-weight:600;font-size:15px">'
                f'{qte:g} action(s)</td></tr>') if qte else ""

    raisonnement = advice.get("raisonnement", "")

    body = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
                max-width:560px;margin:0 auto;padding:24px;color:#111827">
      <p style="font-size:13px;color:#6b7280;margin-bottom:14px">
        Bonjour {username},
      </p>

      <div style="background:#EEF2FF;border-left:4px solid #6366F1;
                  padding:10px 14px;border-radius:4px;margin-bottom:16px">
        <span style="font-size:13px;font-weight:600;color:#3730A3">
          🔔 Votre conseil sur {ticker} a changé
        </span>
        <span style="font-size:15px;color:#6b7280;
                     text-decoration:line-through;margin-left:12px">
          {old_action}
        </span>
        <span style="font-size:15px;color:#374151;margin:0 6px">→</span>
        <span style="font-size:17px;font-weight:700;color:{color}">
          {icon} {new_action}
        </span>
      </div>

      <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
        <tr>
          <td style="padding:8px;color:#6b7280;font-size:13px">Société</td>
          <td style="padding:8px;font-weight:500;font-size:15px">
            {company or ticker} ({ticker})
          </td>
        </tr>
        <tr>
          <td style="padding:8px;color:#6b7280;font-size:13px">Prix actuel</td>
          <td style="padding:8px;font-weight:500;font-size:15px">${prix:.2f}</td>
        </tr>
        {qte_html}
      </table>

      <div style="background:#f8fafc;border:1px solid #e5e7eb;
                  border-radius:6px;padding:12px 14px;margin-bottom:16px;
                  font-size:13px;color:#374151;line-height:1.6">
        <span style="font-size:11px;font-weight:600;color:#6b7280;
                     text-transform:uppercase;letter-spacing:0.05em">
          Raisonnement SDE
        </span><br><br>
        {raisonnement}
      </div>

      <div style="border-top:1px solid #e5e7eb;padding-top:12px;margin-top:4px">
        <a href="{SDE_BASE_URL}/analyze/{ticker}"
           style="display:inline-block;background:#1D9E75;color:#fff;
                  font-size:13px;font-weight:600;text-decoration:none;
                  padding:8px 18px;border-radius:6px;margin-bottom:10px">
          Voir ma position sur {ticker} →
        </a>
        <p style="color:#9ca3af;font-size:11px;margin:0">
          Cet email a été envoyé automatiquement par StockDecisionEngine.
          Outil éducatif — pas un conseil financier.
        </p>
      </div>
    </div>
    """

    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")
    if not api_key:
        print(f"[Mailer] RESEND_API_KEY manquante — email non envoyé à {to_email}", flush=True)
        return
    resend.api_key = api_key
    resend.Emails.send({
        "from":    from_addr,
        "to":      [to_email],
        "subject": subject,
        "html":    body,
    })
    print(f"[Mailer] Conseil position email envoyé à {to_email} "
          f"({ticker} {old_action}→{new_action})", flush=True)
