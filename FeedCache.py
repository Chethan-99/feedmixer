import feedparser
import shelve
import os.path
import datetime
from http.client import NOT_MODIFIED, OK
import re
import logging

logger = logging.getLogger(__name__)

class FeedCache:
    """A wrapper for feedparser which handles caching using the standard shelve
    library. Thread safe but not multi-process safe (doesn't use file system
    lock)."""

    MIN_AGE = 600 # minimum time to keep feed in hard cache

    def __init__(self, db_path):
        logger.debug("Initialized cache: {}".format(db_path))
        self.path = db_path
    
    def get(self, url):
        """Get a feed from the cache db by its url."""
        if os.path.exists(self.path + '.db'):
            with shelve.open(self.path, flag='r') as shelf:
                # TODO: get reader lock
                return shelf.get(url)
        return None

    def update(self, url, feed):
        """Update a feed in the cache db."""
        with shelve.open(self.path, flag='c') as shelf:
            # TODO: get writer lock
            logger.info("Updated feed for url: {}".format(url))
            shelf[url] = feed

    def fetch(self, url):
        etag = None
        lastmod = None
        now = datetime.datetime.now()
        
        logger.debug("Fetching feed for url: {}".format(url))
        cached = self.get(url)
        if cached:
            logger.info("Got feed from cache for url: {}".format(url))
            if now < cached.expire_dt:
                # If cache is fresh, use it without further ado
                logger.info("Fresh feed found in cache: {}".format(url))
                return cached
            
            logger.info("Stale feed found in cache: {}".format(url))
            etag = cached.get('etag')
            lastmod = cached.get('modified')
        else: logger.info("No feed in cache for url: {}".format(url))

        # Cache wasn't fresh in db, so we'll request it, but give origin etag
        # and/or last-modified headers (if available) so we only fetch and
        # parse it if it is new/updated.
        feed = feedparser.parse(url, etag=etag, modified=lastmod)
        logger.debug("Got feed from feedparser: {}".format(feed))

        # TODO: error handling (len(feed.entries) < 1; feed.status == 404, 410, etc)
        
        if feed.status == NOT_MODIFIED:
            # Source says feed is still fresh
            logger.info("Server says feed is still fresh: {}".format(url))
            feed = cached

        # Add to/update cache with new expire_dt
        # Using max-age parsed from cache-control header, if it exists
        cc_header = feed.headers.get('cache-control')
        ma_match = re.search('max-age=(\d+)', cc_header)
        min_age = min(int(ma_match.group(1)), FeedCache.MIN_AGE) if ma_match else MIN_AGE
        feed.expire_dt = now + datetime.timedelta(seconds=min_age)
        self.update(url, feed)
        return feed