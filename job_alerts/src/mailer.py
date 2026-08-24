"""
job_alerts/src/mailer.py
Generation et envoi de l'email de resume des offres
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from .scraper import Job

logger = logging.getLogger(__name__)


def build_html(jobs, date):
    """Genere le corps HTML de l'email."""

    by_source = {}
    for job in jobs:
        by_source.setdefault(job.source, []).append(job)

    source_blocks_parts = []

    for source, source_jobs in by_source.items():
        rows_parts = []
        for j in source_jobs:
            badges = []
            for kw in j.matched_keywords:
                badges.append(
                    '<span style="background:#E8F0FE;color:#1F4E79;padding:2px 8px;'
                    'border-radius:12px;font-size:11px;margin-right:4px;">' + kw + '</span>'
                )
            kw_badges = " ".join(badges)

            row = (
                '<tr>'
                '<td style="padding:12px 8px;border-bottom:1px solid #F0F0F0;vertical-align:top;">'
                '<a href="' + j.url + '" style="color:#1F4E79;font-weight:bold;'
                'text-decoration:none;font-size:14px;">' + j.title + '</a><br>'
                '<span style="color:#595959;font-size:13px;">'
                'Entreprise: ' + j.company + ' | Lieu: ' + j.location + '</span><br>'
                '<div style="margin-top:5px;">' + kw_badges + '</div>'
                '</td>'
                '</tr>'
            )
            rows_parts.append(row)

        rows_html = "".join(rows_parts)

        block = (
            '<div style="margin-bottom:24px;">'
            '<h3 style="color:#2E75B6;border-bottom:2px solid #D6E4F0;'
            'padding-bottom:6px;margin-bottom:0;">' + source + ' - ' +
            str(len(source_jobs)) + ' offre(s)</h3>'
            '<table style="width:100%;border-collapse:collapse;">' + rows_html + '</table>'
            '</div>'
        )
