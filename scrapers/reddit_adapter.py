"""
Reddit sentiment adapter for ChainStaffingTracker.

Uses PRAW (official Reddit API wrapper) when credentials are available,
falls back to public JSON API otherwise. Keyword-scans posts and comments
for staffing-stress signals.

Depends on: praw, requests, config.loader, scrapers.base
Called by: backend/scheduler.py, server.py, CLI
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import (
    get_all_chains,
    get_http_config,
    get_industry,
    get_rate_limit,
    get_region,
)
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)


class RedditAdapter(BaseScraper):
    """Scrapes Reddit for staffing stress and sentiment signals.

    Uses PRAW if REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set.
    Falls back to public JSON API (no auth, lower rate limits).
    """

    name = "Reddit"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limit = get_rate_limit("reddit")
        self.http_cfg = get_http_config()
        self._reddit = None

    def _get_praw_client(self):
        """Initialize PRAW client if credentials available."""
        if self._reddit is not None:
            return self._reddit

        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")

        if client_id and client_secret:
            try:
                import praw
                self._reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=self.http_cfg["user_agent"],
                )
                logger.info("[%s] Using PRAW with API credentials", self.name)
                return self._reddit
            except Exception as e:
                logger.warning("[%s] PRAW init failed, using JSON fallback: %s", self.name, e)

        return None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape Reddit for staffing sentiment signals.

        Args:
            region: Region key from config.
            radius_mi: Not used for Reddit, included for interface compatibility.

        Returns:
            List of ScraperSignal objects. Empty on failure.
        """
        try:
            # Get all industries and their subreddits/keywords
            chains = get_all_chains()
            industries_seen: set[str] = set()
            all_signals: list[ScraperSignal] = []

            for chain_key, chain_cfg in chains.items():
                industry_key = chain_cfg.get("industry", "unknown")
                if industry_key in industries_seen:
                    continue
                industries_seen.add(industry_key)

                try:
                    industry_cfg = get_industry(industry_key)
                except KeyError:
                    continue

                subreddits = industry_cfg.get("subreddits", [])
                keywords = industry_cfg.get("sentiment_keywords", {})
                negative_kw = [kw.lower() for kw in keywords.get("negative", [])]
                positive_kw = [kw.lower() for kw in keywords.get("positive", [])]

                for subreddit in subreddits:
                    posts = self._fetch_posts(subreddit, negative_kw[:5])
                    for post in posts:
                        signal = self._score_post(
                            post, chain_key, region, negative_kw, positive_kw
                        )
                        if signal is not None:
                            all_signals.append(signal)

                    time.sleep(self.rate_limit.get("delay_seconds", 2.0))

            logger.info("[%s] Scraped %d sentiment signals for region=%s", self.name, len(all_signals), region)
            return all_signals

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_posts(self, subreddit: str, search_terms: list[str]) -> list[dict]:
        """Fetch recent posts from a subreddit matching search terms."""
        praw_client = self._get_praw_client()

        if praw_client:
            return self._fetch_via_praw(praw_client, subreddit, search_terms)
        return self._fetch_via_json(subreddit, search_terms)

    def _fetch_via_praw(self, reddit, subreddit: str, search_terms: list[str]) -> list[dict]:
        """Fetch posts using PRAW."""
        posts: list[dict] = []
        try:
            sub = reddit.subreddit(subreddit)
            query = " OR ".join(search_terms[:5])

            for submission in sub.search(query, sort="new", time_filter="month", limit=50):
                posts.append({
                    "title": submission.title,
                    "selftext": submission.selftext,
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                    "created_utc": submission.created_utc,
                    "url": f"https://reddit.com{submission.permalink}",
                    "subreddit": subreddit,
                })
        except Exception as e:
            logger.error("[%s] PRAW fetch failed for r/%s: %s", self.name, subreddit, e)

        return posts

    def _fetch_via_json(self, subreddit: str, search_terms: list[str]) -> list[dict]:
        """Fetch posts using public JSON API (no auth required)."""
        posts: list[dict] = []
        query = " OR ".join(search_terms[:3])

        try:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            resp = requests.get(
                url,
                params={
                    "q": query,
                    "sort": "new",
                    "limit": 50,
                    "restrict_sr": "on",
                    "t": "month",
                },
                headers={"User-Agent": self.http_cfg["user_agent"]},
                timeout=self.http_cfg["timeout_seconds"],
            )
            resp.raise_for_status()
            data = resp.json()

            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                posts.append({
                    "title": post_data.get("title", ""),
                    "selftext": post_data.get("selftext", ""),
                    "score": post_data.get("score", 0),
                    "num_comments": post_data.get("num_comments", 0),
                    "created_utc": post_data.get("created_utc", 0),
                    "url": f"https://reddit.com{post_data.get('permalink', '')}",
                    "subreddit": subreddit,
                })

        except Exception as e:
            logger.error("[%s] JSON API fetch failed for r/%s: %s", self.name, subreddit, e)

        return posts

    def _score_post(
        self,
        post: dict,
        chain_key: str,
        region: str,
        negative_kw: list[str],
        positive_kw: list[str],
    ) -> ScraperSignal | None:
        """Score a single post for staffing stress signals.

        Returns a ScraperSignal with value 0-1 (1 = high stress),
        or None if no relevant keywords found.
        """
        text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()

        # Count keyword hits
        neg_hits = sum(1 for kw in negative_kw if kw in text)
        pos_hits = sum(1 for kw in positive_kw if kw in text)

        if neg_hits == 0 and pos_hits == 0:
            return None  # No relevant content

        # Score: more negative hits = higher stress signal
        total_hits = neg_hits + pos_hits
        stress_ratio = neg_hits / total_hits if total_hits > 0 else 0.5

        # Weight by post engagement
        score_boost = min(1.0, post.get("score", 0) / 100)
        comment_boost = min(1.0, post.get("num_comments", 0) / 50)
        engagement = (score_boost + comment_boost) / 2.0

        # Final value: stress ratio weighted by engagement
        value = (stress_ratio * 0.7) + (engagement * 0.3)
        value = max(0.0, min(1.0, value))

        # Parse timestamp
        created_utc = post.get("created_utc", 0)
        observed_at = datetime.utcfromtimestamp(created_utc) if created_utc else datetime.utcnow()

        return ScraperSignal(
            store_num=f"REGIONAL-{region}",
            chain=chain_key,
            source="reddit",
            signal_type="sentiment",
            value=value,
            metadata={
                "title": post.get("title", ""),
                "subreddit": post.get("subreddit", ""),
                "url": post.get("url", ""),
                "score": post.get("score", 0),
                "num_comments": post.get("num_comments", 0),
                "neg_hits": neg_hits,
                "pos_hits": pos_hits,
                "engagement": round(engagement, 3),
                "store_name": f"Reddit r/{post.get('subreddit', '')}",
                "address": region,
            },
            observed_at=observed_at,
            source_url=post.get("url"),
        )


def scrape_reddit(
    region: str = "austin_tx",
    radius_mi: int = 25,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape Reddit and optionally ingest."""
    adapter = RedditAdapter()
    signals = adapter.scrape(region, radius_mi)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain=None, source="reddit")
        logger.info("[Reddit] Ingested %d signals", count)

    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape Reddit sentiment")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_reddit(region=args.region, ingest=not args.no_ingest)
    logger.info("Scraped %d signals", len(signals))


if __name__ == "__main__":
    main()
