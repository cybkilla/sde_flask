"""
job_alerts/src/main.py
Point d'entrée principal – lancé par GitHub Actions chaque matin
"""

import os
import sys
import logging
import yaml
from pathlib import Path
from .scraper import scrape_indeed, scrape_jobup, scrape_jobscout, Job
from .mailer import send_email

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "keywords.yml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def deduplicate(jobs: list[Job]) -> list[Job]:
    """Supprime les doublons basés sur l'URL."""
    seen = set()
    unique = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            unique.append(job)
    return unique


def filter_jobs(jobs: list[Job], exclude_keywords: list[str]) -> list[Job]:
    """Retire les offres contenant des mots-clés à exclure."""
    filtered = []
    exclude_lower = [kw.lower() for kw in exclude_keywords]
    for job in jobs:
        text = f"{job.title} {job.description}".lower()
        if not any(excl in text for excl in exclude_lower):
            filtered.append(job)
    return filtered


def consolidate_keywords(jobs: list[Job], all_keywords: list[str]) -> list[Job]:
    """Ajoute tous les mots-clés correspondants à chaque offre."""
    for job in jobs:
        text = f"{job.title} {job.description}".lower()
        job.matched_keywords = [kw for kw in all_keywords if kw.lower() in text]
        if not job.matched_keywords:
            job.matched_keywords = ["(correspondance titre)"]
    return jobs


def main():
    logger.info("=== Démarrage de l'alerte emploi ===")

    # 1. Charger la config
    config = load_config()
    keywords: list[str] = config["keywords"]
    locations: list[str] = config["locations"]
    exclude: list[str] = config.get("exclude_keywords", [])
    sources: dict = config.get("sources", {})
    email_cfg: dict = config["email"]

    logger.info(f"Mots-clés : {keywords}")
    logger.info(f"Localisations : {locations}")

    # 2. Scraper les sources activées
    all_jobs: list[Job] = []

    if sources.get("indeed", True):
        logger.info("Scraping Indeed CH...")
        all_jobs += scrape_indeed(keywords, locations)

    if sources.get("jobup", True):
        logger.info("Scraping Jobup.ch...")
        all_jobs += scrape_jobup(keywords, locations)

    if sources.get("jobscout", True):
        logger.info("Scraping Jobscout24.ch...")
        all_jobs += scrape_jobscout(keywords, locations)

    logger.info(f"Total brut : {len(all_jobs)} offres")

    # 3. Dédoublonner et filtrer
    all_jobs = deduplicate(all_jobs)
    all_jobs = filter_jobs(all_jobs, exclude)
    all_jobs = consolidate_keywords(all_jobs, keywords)

    logger.info(f"Total après filtrage : {len(all_jobs)} offres")

    # 4. Récupérer les credentials SMTP depuis les secrets GitHub
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        logger.error("SMTP_USER ou SMTP_PASSWORD non définis dans les secrets GitHub.")
        sys.exit(1)

    # 5. Envoyer l'email (même si aucune offre — pour confirmer que le job tourne)
    send_email(
        jobs=all_jobs,
        to_address=email_cfg["to"],
        subject_template=email_cfg["subject"],
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
    )

    logger.info("=== Terminé ===")


if __name__ == "__main__":
    main()
