"""
job_alerts/src/scraper.py
Scraper multi-sources pour Indeed CH, Jobup.ch et Jobscout24.ch
"""

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import time
import logging
import re

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted: Optional[str] = None
    description: Optional[str] = ""
    matched_keywords: list = field(default_factory=list)

    def __hash__(self):
        return hash(self.url)


# ─────────────────────────────────────────────────────────────
#  INDEED CH
# ─────────────────────────────────────────────────────────────
def scrape_indeed(keywords: list[str], locations: list[str]) -> list[Job]:
    jobs = []
    base = "https://ch.indeed.com/jobs"

    for keyword in keywords:
        for location in locations:
            params = {
                "q": keyword,
                "l": location,
                "fromage": "1",       # offres des dernières 24h
                "sort": "date",
                "lang": "fr",
            }
            try:
                resp = requests.get(base, params=params, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("div", class_=re.compile("job_seen_beacon|resultContent"))

                for card in cards:
                    title_el = card.find("h2", class_=re.compile("jobTitle"))
                    company_el = card.find("span", {"data-testid": "company-name"})
                    location_el = card.find("div", {"data-testid": "text-location"})
                    link_el = card.find("a", href=True)

                    if not title_el or not link_el:
                        continue

                    href = link_el["href"]
                    url = f"https://ch.indeed.com{href}" if href.startswith("/") else href

                    jobs.append(Job(
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True) if company_el else "N/A",
                        location=location_el.get_text(strip=True) if location_el else location,
                        url=url,
                        source="Indeed CH",
                        matched_keywords=[keyword],
                    ))

                time.sleep(1.5)  # pause courtoise

            except Exception as e:
                logger.warning(f"Indeed – erreur pour '{keyword}' / '{location}': {e}")

    return jobs


# ─────────────────────────────────────────────────────────────
#  JOBUP.CH
# ─────────────────────────────────────────────────────────────
def scrape_jobup(keywords: list[str], locations: list[str]) -> list[Job]:
    jobs = []
    base = "https://www.jobup.ch/fr/emplois/"

    for keyword in keywords:
        for location in locations:
            params = {
                "term": keyword,
                "location": location,
                "publication_date": "1",   # 24h
            }
            try:
                resp = requests.get(base, params=params, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("article", class_=re.compile("job-item|JobItem"))

                for card in cards:
                    title_el = card.find(["h2", "h3", "span"], class_=re.compile("title|Title"))
                    company_el = card.find(class_=re.compile("company|Company"))
                    location_el = card.find(class_=re.compile("location|Location"))
                    link_el = card.find("a", href=True)

                    if not title_el or not link_el:
                        continue

                    href = link_el["href"]
                    url = f"https://www.jobup.ch{href}" if href.startswith("/") else href

                    jobs.append(Job(
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True) if company_el else "N/A",
                        location=location_el.get_text(strip=True) if location_el else location,
                        url=url,
                        source="Jobup.ch",
                        matched_keywords=[keyword],
                    ))

                time.sleep(1.5)

            except Exception as e:
                logger.warning(f"Jobup – erreur pour '{keyword}' / '{location}': {e}")

    return jobs


# ─────────────────────────────────────────────────────────────
#  JOBSCOUT24.CH
# ─────────────────────────────────────────────────────────────
def scrape_jobscout(keywords: list[str], locations: list[str]) -> list[Job]:
    jobs = []
    base = "https://www.jobscout24.ch/fr/jobs"

    for keyword in keywords:
        for location in locations:
            params = {
                "query": keyword,
                "location": location,
                "age": "1",
            }
            try:
                resp = requests.get(base, params=params, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all(class_=re.compile("job-list-item|JobListItem|result-item"))

                for card in cards:
                    title_el = card.find(["h2", "h3", "a"], class_=re.compile("title|Title|job-title"))
                    company_el = card.find(class_=re.compile("company|employer"))
                    location_el = card.find(class_=re.compile("location|city"))
                    link_el = card.find("a", href=True)

                    if not title_el or not link_el:
                        continue

                    href = link_el["href"]
                    url = f"https://www.jobscout24.ch{href}" if href.startswith("/") else href

                    jobs.append(Job(
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True) if company_el else "N/A",
                        location=location_el.get_text(strip=True) if location_el else location,
                        url=url,
                        source="Jobscout24.ch",
                        matched_keywords=[keyword],
                    ))

                time.sleep(1.5)

            except Exception as e:
                logger.warning(f"Jobscout24 – erreur pour '{keyword}' / '{location}': {e}")

    return jobs
