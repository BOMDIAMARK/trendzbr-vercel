"""
Instagram Post Scraper using Apify API.
Fetches latest posts from monitored Instagram profiles.
"""
import logging
from typing import Optional

import requests

from lib import config

logger = logging.getLogger("trendzbr.social_scraper")


class InstagramScraper:
    """Fetch latest Instagram posts using Apify's Instagram Post Scraper."""

    APIFY_RUN_URL = "https://api.apify.com/v2/acts/{actor_id}/runs?token={token}"
    APIFY_DATASET_URL = "https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}"

    # Low-cost scraper actor
    ACTOR_ID = "apify~instagram-post-scraper"

    def __init__(self):
        self.api_token = config.APIFY_API_TOKEN

    def fetch_latest_posts(self, username: str, max_posts: int = 5) -> list[dict]:
        """Fetch latest posts from an Instagram profile.

        Returns list of dicts with keys: id, shortcode, caption, url,
        timestamp, media_type, display_url, like_count, comment_count
        """
        if not self.api_token:
            logger.error("APIFY_API_TOKEN not configured")
            return []

        try:
            # Run the actor synchronously (wait for results)
            run_url = (
                f"https://api.apify.com/v2/acts/{self.ACTOR_ID}/run-sync-get-dataset-items"
                f"?token={self.api_token}"
            )

            payload = {
                "username": [username],
                "resultsLimit": max_posts,
            }

            logger.info("Fetching Instagram posts for @%s via Apify", username)
            resp = requests.post(
                run_url,
                json=payload,
                timeout=120,  # Apify can take a while
            )
            resp.raise_for_status()

            posts = resp.json()
            if not isinstance(posts, list):
                logger.warning("Unexpected Apify response format")
                return []

            # Normalize post data
            results = []
            for post in posts:
                normalized = {
                    "id": post.get("id", ""),
                    "shortcode": post.get("shortCode", post.get("shortcode", "")),
                    "caption": (post.get("caption", "") or "")[:500],
                    "url": post.get("url", ""),
                    "timestamp": post.get("timestamp", ""),
                    "media_type": post.get("type", "Image"),
                    "display_url": post.get("displayUrl", ""),
                    "like_count": post.get("likesCount", 0),
                    "comment_count": post.get("commentsCount", 0),
                    "username": username,
                }
                # Build permalink if missing
                if not normalized["url"] and normalized["shortcode"]:
                    normalized["url"] = f"https://www.instagram.com/p/{normalized['shortcode']}/"
                results.append(normalized)

            logger.info("Got %d posts from @%s", len(results), username)
            return results

        except requests.Timeout:
            logger.error("Apify request timed out for @%s", username)
            return []
        except requests.RequestException as e:
            logger.error("Apify request failed for @%s: %s", username, e)
            return []
        except Exception as e:
            logger.error("Error fetching Instagram posts for @%s: %s", username, e)
            return []


class TwitterScraper:
    """Fetch latest tweets using Nitter RSS feed.

    Nitter is an alternative Twitter frontend that provides RSS feeds
    for any public Twitter/X profile. Free, no API key needed.
    """

    # Nitter instances (fallback list in case one goes down)
    NITTER_INSTANCES = [
        "https://nitter.net",
        "https://nitter.space",
        "https://nitter.1d4.us",
        "https://nitter.kavin.rocks",
    ]

    def __init__(self):
        pass

    def fetch_latest_tweets(self, username: str, max_tweets: int = 5) -> list[dict]:
        """Fetch latest tweets from a Twitter/X profile via Nitter RSS."""
        import xml.etree.ElementTree as ET

        rss_content = None
        used_instance = None
        for instance in self.NITTER_INSTANCES:
            try:
                rss_url = f"{instance}/{username}/rss"
                logger.info("Trying Nitter RSS: %s", rss_url)
                resp = requests.get(
                    rss_url,
                    timeout=15,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/rss+xml, application/xml, text/xml",
                    },
                    allow_redirects=True,
                )
                logger.info("Nitter %s status: %d, length: %d", instance, resp.status_code, len(resp.text))
                if resp.status_code == 200 and "<rss" in resp.text:
                    rss_content = resp.text
                    used_instance = instance
                    break
                else:
                    logger.warning("Nitter %s: status %d, has rss: %s", instance, resp.status_code, "<rss" in resp.text)
            except requests.RequestException as e:
                logger.warning("Nitter %s failed: %s", instance, e)
                continue

        if not rss_content:
            logger.error("All Nitter instances failed for @%s", username)
            return []

        try:
            root = ET.fromstring(rss_content)
        except ET.ParseError as e:
            logger.error("Failed to parse Nitter RSS XML: %s", e)
            return []

        items = root.findall(".//item")[:max_tweets]
        logger.info("Parsed %d items from Nitter RSS (%s)", len(items), used_instance)

        results = []
        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")

            title_text = (title_el.text or "").strip() if title_el is not None else ""
            link_text = (link_el.text or "").strip() if link_el is not None else ""

            # Nitter links: https://nitter.net/user/status/123#m
            # Convert to x.com link
            tweet_url = link_text
            tweet_id = ""
            if "/status/" in link_text:
                tweet_id = link_text.split("/status/")[-1].split("#")[0].split("?")[0]
                tweet_url = f"https://x.com/{username}/status/{tweet_id}"

            tweet_text = title_text[:500] if title_text else ""

            # Skip retweets
            if tweet_text.startswith("RT by @"):
                continue

            normalized = {
                "id": tweet_id or link_text,
                "text": tweet_text,
                "url": tweet_url,
                "timestamp": (pub_date_el.text or "").strip() if pub_date_el is not None else "",
                "like_count": 0,
                "retweet_count": 0,
                "reply_count": 0,
                "username": username,
            }
            results.append(normalized)

        logger.info("Got %d tweets from @%s via Nitter (%s)", len(results), username, used_instance)
        return results
