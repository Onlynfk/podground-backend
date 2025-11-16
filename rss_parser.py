"""
RSS Feed Parser utility for extracting podcast information
"""

import feedparser
import logging
from typing import Dict, Optional
from urllib.parse import urlparse
import requests
import ssl
import urllib.request

logger = logging.getLogger(__name__)

class RSSFeedParser:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        # Configure SSL context to handle certificate issues
        self._setup_ssl_context()
    
    def parse_rss_feed(self, rss_url: str) -> Dict:
        """
        Parse RSS feed and extract podcast information
        
        Args:
            rss_url: URL of the RSS feed
            
        Returns:
            Dict with success status and podcast information
        """
        try:
            # Validate URL format
            if not self._is_valid_url(rss_url):
                return {
                    "success": False,
                    "error": "Invalid RSS URL format"
                }
            
            # Set user agent for feedparser to avoid blocking
            feedparser.USER_AGENT = "PodGround/1.0 (+https://podground.com)"
            
            # Parse the RSS feed with custom headers and SSL handling
            logger.info(f"Parsing RSS feed: {rss_url}")
            
            # Create custom request with headers to handle SSL and user agent
            try:
                req = urllib.request.Request(
                    rss_url,
                    headers={
                        'User-Agent': 'PodGround/1.0 (+https://podground.com)',
                        'Accept': 'application/rss+xml, application/xml, text/xml'
                    }
                )
                
                # Use the custom SSL context
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
                    feed_data = response.read()
                
                # Parse the feed data
                feed = feedparser.parse(feed_data)
                
            except Exception as url_error:
                # Fallback to direct feedparser parsing if custom request fails
                logger.warning(f"Custom request failed, falling back to direct parsing: {url_error}")
                feed = feedparser.parse(rss_url)
            
            # Check for parsing errors
            if feed.bozo and feed.bozo_exception:
                logger.warning(f"RSS feed parsing warning: {feed.bozo_exception}")
                # If it's a serious parsing error (not just a warning), fail
                if "syntax error" in str(feed.bozo_exception).lower():
                    return {
                        "success": False,
                        "error": f"RSS feed has invalid XML syntax: {feed.bozo_exception}"
                    }
            
            # Check if feed has required data
            if not hasattr(feed, 'feed') or not feed.feed:
                return {
                    "success": False,
                    "error": "Invalid RSS feed or no feed data found"
                }
            
            # Check if this looks like an HTML page instead of RSS
            if hasattr(feed.feed, 'title') and not hasattr(feed, 'entries'):
                return {
                    "success": False,
                    "error": "URL appears to be a webpage, not an RSS feed. Look for an RSS feed link on the page."
                }
            
            # Extract podcast information
            podcast_info = self._extract_podcast_info(feed)
            
            return {
                "success": True,
                "podcast_info": podcast_info
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error parsing RSS feed {rss_url}: {str(e)}")
            return {
                "success": False,
                "error": f"Network error: Unable to fetch RSS feed"
            }
        except Exception as e:
            logger.error(f"Error parsing RSS feed {rss_url}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to parse RSS feed: {str(e)}"
            }
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except Exception:
            return False
    
    def _extract_podcast_info(self, feed) -> Dict:
        """Extract podcast information from parsed feed"""
        feed_info = feed.feed
        
        # Extract basic podcast information
        title = getattr(feed_info, 'title', '').strip()
        description = getattr(feed_info, 'description', '').strip() or getattr(feed_info, 'subtitle', '').strip()
        link = getattr(feed_info, 'link', '').strip()
        language = getattr(feed_info, 'language', '').strip()
        
        # Extract author/creator information
        author = self._extract_author(feed_info)
        
        # Extract image URL
        image_url = self._extract_image_url(feed_info)
        
        # Count episodes
        episode_count = len(feed.entries) if hasattr(feed, 'entries') else 0
        
        return {
            "title": title,
            "description": description if description else None,
            "link": link if link else None,
            "language": language if language else None,
            "author": author,
            "image_url": image_url,
            "episode_count": episode_count
        }
    
    def _extract_author(self, feed_info) -> Optional[str]:
        """Extract author/creator from various possible fields"""
        # Try different author fields
        author_fields = [
            'author', 'managingEditor', 'webMaster', 'itunes_author'
        ]
        
        for field in author_fields:
            author = getattr(feed_info, field, '').strip()
            if author:
                return author
        
        # Try iTunes-specific tags
        if hasattr(feed_info, 'tags'):
            for tag in feed_info.tags:
                if 'itunes' in tag.get('term', '').lower() and 'author' in tag.get('term', '').lower():
                    return tag.get('label', '').strip()
        
        return None
    
    def _extract_image_url(self, feed_info) -> Optional[str]:
        """Extract podcast image URL from various possible fields"""
        # Try image field
        if hasattr(feed_info, 'image') and hasattr(feed_info.image, 'href'):
            return feed_info.image.href
        
        # Try iTunes image
        if hasattr(feed_info, 'itunes_image') and hasattr(feed_info.itunes_image, 'href'):
            return feed_info.itunes_image.href
        
        # Try tags for image
        if hasattr(feed_info, 'tags'):
            for tag in feed_info.tags:
                if 'image' in tag.get('term', '').lower():
                    return tag.get('label', '').strip()
        
        return None
    
    def _setup_ssl_context(self):
        """Setup SSL context to handle certificate verification issues"""
        try:
            # Create SSL context that's more permissive for development/testing
            self.ssl_context = ssl.create_default_context()
            
            # For production, you might want to be more strict
            # For development, we'll be more permissive to handle certificate issues
            import os
            if os.getenv("ENVIRONMENT", "dev").lower() in ["dev", "development"]:
                self.ssl_context.check_hostname = False
                self.ssl_context.verify_mode = ssl.CERT_NONE
                logger.info("SSL context configured for development (permissive)")
            else:
                logger.info("SSL context configured for production (strict)")
                
        except Exception as e:
            logger.error(f"Failed to setup SSL context: {e}")
            # Fallback to default context
            self.ssl_context = ssl.create_default_context()