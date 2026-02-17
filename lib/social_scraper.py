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
                "directUrls": [f"https://www.instagram.com/{username}/"],
                "resultsLimit": max_posts,
                "resultsType": "posts",
                "searchType": "user",
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
    """Fetch latest tweets using Apify's Twitter Scraper.

    Note: This is a fallback — the primary Twitter solution is the
    Twitgram Bot (@TwitGram_Robot) on Telegram which handles forwarding
    automatically. This scraper is only used if Twitgram is not sufficient.
    """

    ACTOR_ID = "apify~twitter-scraper"

    def __init__(self):
        self.api_token = config.APIFY_API_TOKEN

    def fetch_latest_tweets(self, username: str, max_tweets: int = 5) -> list[dict]:
        """Fetch latest tweets from a Twitter/X profile."""
        if not self.api_token:
            logger.error("APIFY_API_TOKEN not configured")
            return []

        try:
            run_url = (
                f"https://api.apify.com/v2/acts/{self.ACTOR_ID}/run-sync-get-dataset-items"
                f"?token={self.api_token}"
            )

            payload = {
                "twitterHandles": [username],
                "maxTweets": max_tweets,
                "mode": "user",
            }

            logger.info("Fetching tweets for @%s via Apify", username)
            resp = requests.post(run_url, json=payload, timeout=120)
            resp.raise_for_status()

            tweets = resp.json()
            if not isinstance(tweets, list):
                logger.warning("Unexpected Apify response format for Twitter")
                return []

            results = []
            for tweet in tweets:
                normalized = {
                    "id": tweet.get("id", ""),
                    "text": (tweet.get("text", tweet.get("full_text", "")) or "")[:500],
                    "url": tweet.get("url", ""),
                    "timestamp": tweet.get("createdAt", ""),
                    "like_count": tweet.get("likeCount", 0),
                    "retweet_count": tweet.get("retweetCount", 0),
                    "reply_count": tweet.get("replyCount", 0),
                    "username": username,
                }
                if not normalized["url"] and normalized["id"]:
                    normalized["url"] = f"https://x.com/{username}/status/{normalized['id']}"
                results.append(normalized)

            logger.info("Got %d tweets from @%s", len(results), username)
            return results

        except requests.Timeout:
            logger.error("Apify request timed out for Twitter @%s", username)
            return []
        except requests.RequestException as e:
            logger.error("Apify request failed for Twitter @%s: %s", username, e)
            return []
        except Exception as e:
            logger.error("Error fetching tweets for @%s: %s", username, e)
            return []
