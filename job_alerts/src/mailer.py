"""
job_alerts/src/mailer.py
Génération et envoi de l'email de résumé des offres
"""

import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional
from .scraper import Job

logger = logging.getLogger(__name__)


def build_html(jobs: list[Job], date: str) -> str:
    """Génère le corps HTML de l'email."""

    # Grouper par source
    by_source: dict[str, list[Job]] = {}
    for job in jobs:
        by_source.setdefault(job.source, []).append(job)

    source_blocks = ""
    for source, source_jobs in by_source.items():
        rows = ""
        for j in source_jobs:
            kw_badges = " ".join(
                f'<span style="background:#E8F0FE;color:#1F4E79;padding:2px 8px;'
                f'border-radius:12px;font-size:11px;margin-right:4px;">{kw}</span>'
                for kw in j.matched_keywords
            )
            rows += f"""
            <tr>
              <td style="padding:12px 8px;border-bottom:1px solid #F0F0F0;vertical-align:top;">
                <a href="{j.url}" style="color:#1F4E79;font-weight:bold;text-decoration:none;font-size:14px;">
                  {j.title}
                </a><br>
                <span style="color:#595959;font-size:13px;">🏢 {j.company} &nbsp;|&nbsp; 📍 {j.location}</span><br>
                <div style="margin-top:5px;">{kw_badges}</div>
              </td>
            </tr>"""

        source_blocks += f"""
        <div style="margin-bottom:24px;">
          <h3 style="color:#2E75B6;border-bottom:2px solid #D6E4F0;padding-bottom:6px;margin-bottom:0;">
            {source} — {len(source_jobs)} offre(s)
          </h3>
          <table style="width:100%;border-collapse:collapse;">{rows}</table>
        </div>"""

    total = len(jobs)
    no_jobs_message = '<p style="color:#595959;text-align:center;">Aucune nouvelle offre aujourd’hui.</p>'
    body_content = source_blocks if source_blocks else no_jobs_message

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#1A1A1A;">

      <!-- HEADER -->
      <div style="background:#1F4E79;padding:24px 28px;border-radius:8px 8px 0 0;">
        <h1 style="color:#FFFFFF;margin:0;font-size:22px;">🔔 Nouvelles offres d'emploi</h1>
        <p style="color:#D6E4F0;margin:6px 0 0;">{date} &nbsp;·&nbsp; {total} offre(s) trouvée(s)</p>
      </div>

      <!-- BODY -->
      <div style="background:#FAFAFA;padding:24px 28px;border:1px solid #E0E0E0;border-top:none;">
        {body_content}
      </div>

      <!-- FOOTER -->
      <div style="background:#F2F2F2;padding:14px 28px;border-radius:0 0 8px 8px;
                  border:1px solid #E0E0E0;border-top:none;text-align:center;">
        <p
