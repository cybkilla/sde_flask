import os, sys, logging, yaml
from pathlib import Path
from .scraper import scrape_indeed, scrape_jobup, scrape_jobscout, Job
from .mailer import send_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

def load_config():
    config_path = Path(__file__).parent.parent / "config" / "keywords.yml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def deduplicate(jobs):
    seen = set()
    result = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            result.append(job)
    return result

def filter_jobs(jobs, exclude_keywords):
    exclude_lower = [kw.lower() for kw in exclude_keywords]
    result = []
    for job in jobs:
        text = (job.title + " " + (job.description or "")).lower()
        if not any(excl in text for excl in exclude_lower):
            result.append(job)
    return result

def filter_french(jobs):
    markers = ["m/w/d", "mitarbeiter", "sachbearbeiter", "kaufmann", "kauffrau", "gesucht", "wir suchen", "ihre aufgaben", "erfahrung in", "kenntnisse", "und", "der", "die", "das", "mit", "fur", "eine", "einen", "ist", "sind", "wird", "ihre", "unsere", "unser", "auf", "von", "im", "am", "bei", "aufgaben", "anforderungen", "unternehmen", "stelle als", "tatigkeit", "abteilung", "mind.", "wir bieten", "ihr profil", "zuerich", "zurich", "bern", "basel"]
    result = []
    for job in jobs:
        text = (job.title + " " + job.location).lower()
        hits = sum(1 for w in markers if w in text)
        if hits == 0:
            result.append(job)
    return result

def consolidate_keywords(jobs, all_keywords):
    for job in jobs:
        text = (job.title + " " + (job.description or "")).lower()
        job.matched_keywords = [kw for kw in all_keywords if kw.lower() in text]
        if not job.matched_keywords:
            job.matched_keywords = ["(titre)"]
    return jobs

def main():
    logger.info("=== Demarrage ===")
    config = load_config()
    keywords = config["keywords"]
    locations = config["locations"]
    exclude = config.get("exclude_keywords", [])
    sources = config.get("sources", {})
    email_cfg = config["email"]

    all_jobs = []
    if sources.get("indeed", True):
        all_jobs += scrape_indeed(keywords, locations)
    if sources.get("jobup", True):
        all_jobs += scrape_jobup(keywords, locations)
    if sources.get("jobscout", True):
        all_jobs += scrape_jobscout(keywords, locations)

    logger.info("Total brut : " + str(len(all_jobs)))

    all_jobs = deduplicate(all_jobs)
    all_jobs = filter_jobs(all_jobs, exclude)
    all_jobs = filter_french(all_jobs)
    all_jobs = consolidate_keywords(all_jobs, keywords)

    logger.info("Total apres filtrage : " + str(len(all_jobs)))

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        logger.error("SMTP_USER ou SMTP_PASSWORD manquants")
        sys.exit(1)

    send_email(all_jobs, email_cfg["to"], email_cfg["subject"], smtp_host, smtp_port, smtp_user, smtp_password)
    logger.info("=== Termine ===")

if __name__ == "__main__":
    main()
    
