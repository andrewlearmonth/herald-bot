import os
import time
import logging
import requests
import re
from bs4 import BeautifulSoup
import tweepy
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()

class HeraldBot:
    BASE_URL = "https://www.heraldscotland.com"
    POLITICS_URL = f"{BASE_URL}/politics/"
    LOG_FILE = "posted_urls.txt"
    MAX_TWEETS = 2
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    def __init__(self):
        self.client = tweepy.Client(
            consumer_key=os.getenv("TWITTER_API_KEY"),
            consumer_secret=os.getenv("TWITTER_API_SECRET"),
            access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
            access_token_secret=os.getenv("TWITTER_ACCESS_SECRET")
        )

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("herald_bot.log"),
                logging.StreamHandler()
            ]
        )

    def load_posted_urls(self):
        if os.path.exists(self.LOG_FILE):
            with open(self.LOG_FILE, 'r') as f:
                return set(line.strip() for line in f)
        return set()

    def save_posted_urls(self, urls):
        with open(self.LOG_FILE, 'w') as f:
            for url in sorted(urls):
                f.write(f"{url}\n")

    def fetch_article_urls(self):
        try:
            response = requests.get(self.POLITICS_URL, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            urls = []

            for link in soup.find_all('a', href=True):
                href = link['href'].split('#')[0]
                if not href.startswith('/'):
                    continue
                if not re.search(r'/\d{8,}\.', href):
                    continue
                full_url = self.BASE_URL + href.split('?')[0]
                if full_url not in urls:
                    urls.append(full_url)

            logging.info(f"Found {len(urls)} article URLs.")
            return urls
        except Exception as e:
            logging.error(f"Failed to fetch article links: {e}")
            return []

    def extract_article_info(self, url):
        try:
            response = requests.get(url, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            headline_tag = soup.find('h1')
            headline = headline_tag.get_text(strip=True) if headline_tag else None

            time_tag = soup.find('time')
            if time_tag and time_tag.has_attr('datetime'):
                published = datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00')).astimezone(timezone.utc)
            else:
                published = None

            author_tag = soup.find('a', class_='author-name')
            author_name = None
            if author_tag:
                author_text = author_tag.get_text(strip=True)
                if " by " in author_text:
                    author_name = author_text.split(" by ", 1)[-1]
                else:
                    author_name = author_text

            twitter_tag = soup.find('a', class_='twitter-link')
            twitter_handle = None
            if twitter_tag and twitter_tag.get_text(strip=True).startswith('@'):
                twitter_handle = twitter_tag.get_text(strip=True)

            logging.info(f"Extracted info for {url}: headline='{headline}', author='{author_name}', twitter_handle='{twitter_handle}'")
            return headline, published, twitter_handle
        except Exception as e:
            logging.warning(f"Could not extract article info from {url}: {e}")
            return None, None, None

    def post_to_x(self, headline, url, twitter_handle=None):
        handles = []
        if twitter_handle:
            handles.append(twitter_handle)

        text = f"{headline} {url} {' '.join(handles)}"
        text = text[:280]

        try:
            self.client.create_tweet(text=text)
            logging.info(f"Tweeted: {text}")
            return True
        except tweepy.TooManyRequests as e:
            logging.error(f"Twitter rate limit hit: {e}")
            time.sleep(60)
            return False
        except Exception as e:
            logging.error(f"Twitter error: {e}")
            return False

    def run(self):
        logging.info("Starting Herald bot run.")
        posted_urls = self.load_posted_urls()
        new_urls = set()
        tweets_sent = 0

        for url in self.fetch_article_urls():
            logging.info(f"Checking URL: {url}")

            if tweets_sent >= self.MAX_TWEETS:
                logging.info("Max tweets reached.")
                break
            if url in posted_urls:
                logging.info(f"Already posted: {url}")
                continue

            headline, published, twitter_handle = self.extract_article_info(url)
            if not headline or not published:
                logging.info(f"Skipping article due to missing headline or publish time: {url}")
                continue

            age = datetime.now(timezone.utc) - published
            if age.total_seconds() > 86400:
                logging.info(f"Article too old: {url} (published at {published})")
                continue

            if self.post_to_x(headline, url, twitter_handle):
                new_urls.add(url)
                tweets_sent += 1
                time.sleep(40)  # Increased delay to reduce risk of rate limits

        posted_urls.update(new_urls)
        self.save_posted_urls(posted_urls)
        logging.info("Herald bot finished run.")

if __name__ == "__main__":
    print("Running Herald Bot...")
    bot = HeraldBot()
    bot.run()
    print("Done!")
