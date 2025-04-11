import os
import time
import logging
import requests
import re
from bs4 import BeautifulSoup
from atproto import Client as BskyClient
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.heraldscotland.com"
POLITICS_URL = f"{BASE_URL}/politics/"
LOG_FILE = "posted_urls_bsky.txt"
MAX_POSTS = 2
HEADERS = {"User-Agent": "Mozilla/5.0"}

BSKY_HANDLE = os.getenv("BSKY_HANDLE")
BSKY_APP_PASSWORD = os.getenv("BSKY_APP_PASSWORD")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bluesky_bot.log"),
        logging.StreamHandler()
    ]
)

def load_posted_urls():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()

def save_posted_urls(urls):
    with open(LOG_FILE, 'w') as f:
        for url in sorted(urls):
            f.write(f"{url}\n")

def fetch_article_urls():
    try:
        response = requests.get(POLITICS_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        urls = []
        for link in soup.find_all('a', href=True):
            href = link['href'].split('#')[0]
            if not href.startswith('/'):
                continue
            if not re.search(r'/\d{8,}\.', href):
                continue
            full_url = BASE_URL + href.split('?')[0]
            if full_url not in urls:
                urls.append(full_url)
        logging.info(f"Found {len(urls)} article URLs.")
        return urls
    except Exception as e:
        logging.error(f"Failed to fetch article links: {e}")
        return []

def extract_article_info(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        headline_tag = soup.find('h1')
        headline = headline_tag.get_text(strip=True) if headline_tag else None

        time_tag = soup.find('time')
        if time_tag and time_tag.has_attr('datetime'):
            published = datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
        else:
            published = None

        return headline, published
    except Exception as e:
        logging.warning(f"Could not extract article info from {url}: {e}")
        return None, None

def post_to_bluesky(headline, url):
    if not BSKY_HANDLE or not BSKY_APP_PASSWORD:
        logging.warning("Bluesky credentials not set.")
        return

    message = f"{headline}\n{url}"
    try:
        client = BskyClient()
        client.login(BSKY_HANDLE, BSKY_APP_PASSWORD)
        client.send_post(message)
        logging.info(f"Posted to Bluesky: {message}")
    except Exception as e:
        logging.error(f"Bluesky post failed: {e}")

def run():
    logging.info("Starting Bluesky bot run.")
    posted_urls = load_posted_urls()
    new_urls = set()
    posts_sent = 0

    for url in fetch_article_urls():
        logging.info(f"Checking URL: {url}")

        if posts_sent >= MAX_POSTS:
            logging.info("Max posts reached.")
            break
        if url in posted_urls:
            logging.info(f"Already posted: {url}")
            continue

        headline, published = extract_article_info(url)
        if not headline or not published:
            logging.info(f"Skipping article due to missing headline or publish time: {url}")
            continue

        age = datetime.now(timezone.utc) - published
        if age.total_seconds() > 86400:
            logging.info(f"Article too old: {url} (published at {published})")
            continue

        post_to_bluesky(headline, url)
        new_urls.add(url)
        posts_sent += 1
        time.sleep(40)

    posted_urls.update(new_urls)
    save_posted_urls(posted_urls)
    logging.info("Bluesky bot finished run.")

if __name__ == "__main__":
    print("Running Bluesky Bot...")
    run()
    print("Done!")
