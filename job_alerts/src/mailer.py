import smtplib, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
logger = logging.getLogger(__name__)

def build_html(jobs, date):
    lines = []
    for j in jobs:
        kw = ", ".join(j.matched_keywords)
        lines.append('<p><a href="' + j.url + '">' + j.title + '</a><br>' + j.company + ' - ' + j.location + '<br>Source: ' + j.source + ' | Mots-cles: ' + kw + '</p><hr>')
    body = "".join(lines) if lines else "<p>Aucune nouvelle offre aujourd hui.</p>"
    return '<html><body><h2>Offres emploi - ' + date + '</h2><p>' + str(len(jobs)) + ' offre(s) trouvee(s)</p>' + body + '</body></html>'

def send_email(jobs, to_address, subject_template, smtp_host, smtp_port, smtp_user, smtp_password, use_tls=True):
    date_str = datetime.now().strftime("%d/%m/%Y")
    subject = subject_template.format(date=date_str)
    html_body = build_html(jobs, date_str)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if use_tls:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port)
    server.login(smtp_user, smtp_password)
    server.sendmail(smtp_user, to_address, msg.as_string())
    server.quit()
    logger.info("Email envoye a " + to_address)
