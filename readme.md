# Herald Bot 📰🤖

This is a Python bot that scrapes the latest articles from the [Herald Scotland](https://www.heraldscotland.com/politics/) politics section and posts them to X (Twitter).

## Features
- Tweets new Herald politics articles
- Tags authors where possible
- Avoids reposting the same article
- Skips articles older than 24 hours

## Setup

1. Clone this repo
2. Create a `.env` file with your X API keys:
    ```env
    TWITTER_API_KEY=...
    TWITTER_API_SECRET=...
    TWITTER_ACCESS_TOKEN=...
    TWITTER_ACCESS_SECRET=...
    ```
3. Install dependencies:
    ```
    pip install -r requirements.txt
    ```

4. Run the bot:
    ```
    python herald_bot.py
    ```

## Notes
- Only posts up to 2 new stories per run
- Uses `posted_urls.txt` to track what’s already been posted
- Add author handles in the `AUTHOR_HANDLES` dictionary in `herald_bot.py`

## License
MIT — do what you like with it
