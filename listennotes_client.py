import os
from typing import Dict, List, Optional
import logging
import html
from listennotes import podcast_api

logger = logging.getLogger(__name__)

class ListenNotesClient:
    def __init__(self):
        self.api_key = os.getenv("LISTENNOTES_API_KEY")
        
        if not self.api_key:
            logger.warning("ListenNotes API key not found in environment variables")
            self.client = None
        else:
            try:
                self.client = podcast_api.Client(api_key=self.api_key)
                logger.info("ListenNotes client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ListenNotes client: {str(e)}")
                self.client = None
    
    def _safe_api_call(self, api_method, *args, **kwargs) -> Dict:
        """Safely call ListenNotes API methods with error handling and timeout management"""
        if not self.client:
            return {"success": False, "error": "ListenNotes client not initialized"}
        
        try:
            # Add timeout to kwargs if not already present
            if 'timeout' not in kwargs:
                kwargs['timeout'] = 15  # Reduce timeout to 15 seconds
            
            response = api_method(*args, **kwargs)
            
            # Handle different response types from ListenNotes API
            if hasattr(response, 'json'):
                # If it's a requests Response object, get the JSON
                response_data = response.json()
            elif hasattr(response, 'get'):
                # If it's already a dict, use it directly
                response_data = response
            else:
                # If it's some other object, try to convert or log the type
                logger.warning(f"Unexpected response type: {type(response)}")
                response_data = response
            
            return {"success": True, "data": response_data}
        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "read timed out" in error_msg.lower():
                logger.warning(f"ListenNotes API timeout: {error_msg}")
                return {"success": False, "error": "API request timed out"}
            else:
                logger.error(f"ListenNotes API call failed: {error_msg}")
                return {"success": False, "error": f"API call failed: {error_msg}"}
    
    def search_podcasts(self, query: str, limit: int = 10, offset: int = 0) -> Dict:
        """Search for podcasts with exact title matching using broader search + client-side filtering"""
        try:
            logger.info(f"Searching for exact title match: {query}")
            
            # Use broader search without quotes to get candidates
            result = self._safe_api_call(
                self.client.search,
                q=query,  # No quotes for broader search
                type='podcast',
                sort_by_date=0,
                offset=offset,
                len_min=0,  # Remove minimum length restriction
                published_after=0,
                only_in='title',
                language='English',
                safe_mode=0,
                unique_podcasts=0,
                interviews_only=0,
                sponsored_only=0,
                page_size=10,  # Match the sample code
            )
            
            if result["success"] and result.get("data"):
                # Check if data is a string (error case) or dict (success case)
                if isinstance(result["data"], str):
                    logger.warning(f"API returned string instead of data: {result['data']}")
                    return {"success": False, "error": f"API error: {result['data']}"}
                
                # Get all results for client-side filtering
                all_results = result["data"].get("results", []) if isinstance(result["data"], dict) else []
                
                if all_results:
                    logger.info(f"Got {len(all_results)} results from broader search, filtering for exact matches...")
                    
                    # Filter for exact title matches (case-insensitive)
                    exact_matches = []
                    query_lower = query.lower().strip()
                    
                    for podcast in all_results:
                        # Decode HTML entities for proper comparison (e.g., &amp; -> &)
                        title_raw = podcast.get("title_original", "")
                        title = html.unescape(title_raw).lower().strip()
                        if title == query_lower:
                            logger.info(f"Found exact match: '{title_raw}'")
                            exact_matches.append({
                                "id": podcast.get("id"),
                                "title": html.unescape(title_raw),
                                "description": html.unescape(podcast.get("description_original", "")),
                                "image": podcast.get("image", ""),
                                "publisher": html.unescape(podcast.get("publisher_original", "")),
                                "email": podcast.get("email", "")
                            })
                    
                    if exact_matches:
                        return {
                            "success": True,
                            "results": exact_matches[:limit],  # Limit results
                            "total": len(exact_matches)
                        }
                    else:
                        logger.info("No exact title matches found")
                        # Show available titles for debugging
                        logger.info("Available titles found:")
                        for i, podcast in enumerate(all_results[:5]):
                            logger.info(f"  {i+1}. '{podcast.get('title_original', '')}'")
                        
                        return {"success": True, "results": [], "total": 0}
                else:
                    logger.info("No results found from broader search")
                    return {"success": True, "results": [], "total": 0}
            else:
                logger.warning(f"Search failed: {result.get('error', 'Unknown error')}")
                return {"success": False, "error": result.get("error", "Search failed")}
                
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return {"success": False, "error": f"Search failed: {str(e)}"}
    
    def get_podcast_details(self, podcast_id: str) -> Dict:
        """Get detailed information about a specific podcast"""
        try:
            # Use the official library's fetch_podcast_by_id method
            result = self._safe_api_call(
                self.client.fetch_podcast_by_id,
                id=podcast_id
            )
            
            if result["success"]:
                podcast = result["data"]
                # Decode HTML entities (e.g., &amp; -> &)
                return {
                    "success": True,
                    "podcast": {
                        "id": podcast.get("id"),
                        "title": html.unescape(podcast.get("title_original", "")),
                        "description": html.unescape(podcast.get("description_original", "")),
                        "image": podcast.get("image", ""),
                        "publisher": html.unescape(podcast.get("publisher_original", "")),
                        "website": podcast.get("website", ""),
                        "rss": podcast.get("rss", ""),
                        "email": podcast.get("email", ""),  # Direct email access!
                        "total_episodes": podcast.get("total_episodes", 0),
                        "genre_ids": podcast.get("genre_ids", []),
                        "thumbnail": podcast.get("thumbnail", ""),
                        "language": podcast.get("language", ""),
                        "explicit_content": podcast.get("explicit_content", False)
                    }
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Get podcast details failed: {str(e)}")
            return {"success": False, "error": f"Get details failed: {str(e)}"}
    
    def typeahead_search(self, query: str, limit: int = 10) -> Dict:
        """Typeahead search for podcasts - optimized for quick suggestions"""
        try:
            # Use the official library's typeahead search method
            result = self._safe_api_call(
                self.client.typeahead,
                q=query,
                show_podcasts=1,
                show_genres=0,
                safe_mode=0
            )
            
            if result["success"]:
                # Transform the response to match our model
                podcasts = []
                for podcast in result["data"].get("podcasts", [])[:limit]:
                    # Decode HTML entities (e.g., &amp; -> &)
                    podcasts.append({
                        "id": podcast.get("id"),
                        "title": html.unescape(podcast.get("title_original", "")),
                        "description": html.unescape(podcast.get("description_original", "")),
                        "publisher": html.unescape(podcast.get("publisher_original", "")),
                        "image": podcast.get("image", ""),
                        "email": podcast.get("email", "")
                    })
                
                return {
                    "success": True,
                    "results": podcasts,
                    "total": len(podcasts)
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Typeahead search failed: {str(e)}")
            return {"success": False, "error": f"Typeahead search failed: {str(e)}"}
    
    def get_podcast_by_id(self, podcast_id: str) -> Dict:
        """Get podcast details by ID from ListenNotes"""
        try:
            logger.info(f"Fetching podcast details for ID: {podcast_id}")
            
            result = self._safe_api_call(
                self.client.fetch_podcast_by_id,
                id=podcast_id
            )
            
            if result["success"] and result.get("data"):
                data = result["data"]

                # Decode HTML entities (e.g., &amp; -> &)
                return {
                    "success": True,
                    "data": {
                        "id": data.get("id"),
                        "title": html.unescape(data.get("title", "")),
                        "publisher": html.unescape(data.get("publisher", "")),
                        "image": data.get("image"),
                        "description": html.unescape(data.get("description", "")),
                        "email": data.get("email", ""),
                        "website": data.get("website", ""),
                        "total_episodes": data.get("total_episodes", 0),
                        "genre_ids": data.get("genre_ids", []),
                        "rss": data.get("rss", ""),
                        "thumbnail": data.get("thumbnail", ""),
                        "language": data.get("language", ""),
                        "explicit_content": data.get("explicit_content", False)
                    }
                }
            else:
                logger.warning(f"Failed to fetch podcast {podcast_id}: {result.get('error')}")
                return {"success": False, "error": result.get("error", "Podcast not found")}
                
        except Exception as e:
            logger.error(f"Fetch podcast by ID failed: {str(e)}")
            return {"success": False, "error": f"Fetch podcast failed: {str(e)}"}

