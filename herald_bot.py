import os
import time
import logging
import requests
import re
from bs4 import BeautifulSoup
import tweepy
from datetime import datetime, timezone
from dotenv import load_dotenv
from atproto import Client as BskyClient
import fcntl
import uuid

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

        self.bsky_handle = os.getenv("BSKY_HANDLE")
        self.bsky_password = os.getenv("BSKY_APP_PASSWORD")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("herald_bot.log"),
                logging.StreamHandler()
            ]
        )
        self.lock_file = None

    def acquire_lock(self):
        """Ensure only one instance of the bot runs using a lock file."""
        try:
            self.lock_file = open("bot.lock", "w")
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logging.info("Acquired bot lock.")
            return True
        except IOError:
            logging.error("Another instance of the bot is running.")
            return False

    def release_lock(self):
        """Release the lock file."""
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None
            logging.info("Released bot lock.")

    def load_posted_urls(self):
        """Load previously posted URLs with file locking."""
        if not os.path.exists(self.LOG_FILE):
            return set()
        with open(self.LOG_FILE, 'r') as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
                urls = set(line.strip() for line in f)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Release lock
                logging.info(f"Loaded {len(urls)} previously posted URLs.")
                return urls
            except Exception as e:
                logging.error(f"Error loading posted URLs: {e}")
                return set()

    def save_posted_urls(self, urls):
        """Save posted URLs with file locking."""
        with open(self.LOG_FILE, 'w') as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock for writing
                for url in sorted(urls):
                    f.write(f"{url}\n")
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Release lock
                logging.info(f"Saved {len(urls)} posted URLs.")
            except Exception as e:
                logging.error(f"Error saving posted URLs: {e}")

    def fetch_article_urls(self):
        """Fetch and normalize article URLs from the politics page."""
        try:
            response = requests.get(self.POLITICS_URL, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            urls = set()  # Use set to avoid duplicates within a run

            for link in soup.find_all('a', href=True):
                href = link['href'].split('#')[0]
                if not href.startswith('/'):
                    continue
                if not re.search(r'/\d{8,}\.', href):
                    continue
                full_url = (self.BASE_URL + href.split('?')[0]).rstrip('/').lower()  # Normalize
                urls.add(full_url)

            logging.info(f"Found {len(urls)} article URLs: {urls}")
            return list(urls)
        except Exception as e:
            logging.error(f"Failed to fetch article links: {e}")
            return []

    def extract_article_info(self, url):
        """Extract headline, publication time, and Twitter handle from an article."""
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

    def has_recently_posted(self, url):
        """Check if the URL was recently posted by querying recent tweets."""
        try:
            tweets = self.client.get_users_tweets(id=self.client.get_me().data.id, max_results=10)
            for tweet in tweets.data:
                if url in tweet.text:
                    logging.info(f"Found recent post containing URL: {url}")
                    return True
            return False
        except Exception as e:
            logging.error(f"Error checking recent tweets: {e}")
            return False

    def post_to_x(self, headline, url, twitter_handle=None):
        """Post an article to X and log the URL immediately if successful."""
        if self.has_recently_posted(url):
            logging.info(f"URL {url} was recently posted, skipping.")
            return False

        handles = [twitter_handle] if twitter_handle else []
        text = f"{headline} {url} {' '.join(handles)}"[:280]

        try:
            self.client.create_tweet(text=text)
            logging.info(f"Tweeted to X: {text}")
            # Log URL immediately
            posted_urls = self.load_posted_urls()
            posted_urls.add(url)
            self.save_posted_urls(posted_urls)
            return True
        except tweepy.TooManyRequests as e:
            logging.error(f"Twitter rate limit hit: {e}")
            time.sleep(60)
            return False
        except Exception as e:
            logging.error(f"Twitter error: {e}")
            return False

    def post_to_bluesky(self, headline, url):
        """Post an article to Bluesky."""
        if not self.bsky_handle or not self.bsky_password:
            logging.warning("Bluesky credentials not set.")
            return

        message = f"{headline}\n{url}"
        try:
            client = BskyClient()
            client.login(self.bsky_handle, self.bsky_password)
            client.send_post(message)
            logging.info(f"Posted to Bluesky: {message}")
        except Exception as e:
            logging.error(f"Bluesky post failed: {e}")

    def run(self):
        """Main bot logic to fetch and post articles."""
        if not self.acquire_lock():
            return
        try:
            logging.info("Starting Herald bot run.")
            posted_urls = self.load_posted_urls()
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
                    self.post_to_bluesky(headline, url)
                    tweets_sent += 1
                    time.sleep(40)

            logging.info("Herald bot finished run.")
        finally:
            self.release_lock()

if __name__ == "__main__":
    print("Running Herald Bot...")
    bot = HeraldBot()
    bot.run()
    print("Done!")
