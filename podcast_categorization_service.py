"""
Podcast Categorization Service
Uses Google Gemini AI to categorize podcasts based on their descriptions
"""
import os
import logging
import asyncio
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from supabase import Client
import json

logger = logging.getLogger(__name__)

class PodcastCategorizationService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
        
        if not self.gemini_api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            raise ValueError("GEMINI_API_KEY is required")
        
        # Configure Gemini
        genai.configure(api_key=self.gemini_api_key)
        model_name = os.getenv('GEMINI_MODEL_NAME', 'gemini-1.5-flash')
        self.model = genai.GenerativeModel(model_name)
        logger.info(f"Using Gemini model: {model_name}")
        
    async def get_uncategorized_podcasts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get podcasts that don't have any category mappings"""
        try:
            # First, get all podcast IDs that have mappings
            mapped_result = self.supabase.table('podcast_category_mappings') \
                .select('podcast_id') \
                .execute()
            
            mapped_ids = [m['podcast_id'] for m in mapped_result.data] if mapped_result.data else []
            
            # Get podcasts that are not in the mapped list
            query = self.supabase.table('podcasts') \
                .select('id, listennotes_id, title, description, publisher') \
                .limit(limit)
            
            if mapped_ids:
                # Get podcasts whose IDs are not in the mapped list
                all_podcasts_result = query.execute()
                uncategorized = [p for p in all_podcasts_result.data if p['id'] not in mapped_ids]
                return uncategorized[:limit]
            else:
                # If no mappings exist, just get the first batch of podcasts
                result = query.execute()
                return result.data if result.data else []
                
        except Exception as e:
            logger.error(f"Error getting uncategorized podcasts: {e}")
            return []
    
    async def get_all_categories(self) -> List[Dict[str, Any]]:
        """Get all active podcast categories"""
        try:
            result = self.supabase.table('podcast_categories') \
                .select('id, name, display_name, description') \
                .eq('is_active', True) \
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting categories: {e}")
            return []
    
    async def fetch_podcast_details_from_listennotes(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed podcast information from ListenNotes API"""
        if not self.listennotes_api_key or not listennotes_id:
            return None
        
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': self.listennotes_api_key}
                response = await client.get(
                    f"https://listen-api.listennotes.com/api/v2/podcasts/{listennotes_id}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"ListenNotes API error: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching from ListenNotes: {e}")
            return None
    
    async def search_web_for_podcast_info(self, title: str, publisher: str) -> Optional[str]:
        """Search web for additional podcast information when ListenNotes data is insufficient"""
        try:
            search_query = f'podcast "{title}"'
            if publisher:
                search_query += f' by {publisher}'
            search_query += ' description about topics'
            
            logger.info(f"Searching web for additional info: {search_query}")
            
            # Use Gemini to search and summarize web results
            web_search_prompt = f"""
Search the web for information about this podcast and provide a brief summary:

Podcast: {title}
Publisher: {publisher}

Please find and summarize:
1. What topics does this podcast cover?
2. Who is the target audience?
3. What is the podcast format/style?
4. Any notable themes or focus areas?

Provide a concise 100-200 word summary focusing on content and themes.
"""
            
            response = self.model.generate_content(web_search_prompt)
            web_summary = response.text.strip()
            logger.info(f"Web search provided summary for '{title}'")
            return web_summary
            
        except Exception as e:
            logger.error(f"Error searching web for podcast info: {e}")
            return None
    
    async def categorize_podcast_with_gemini(self, podcast: Dict[str, Any], categories: List[Dict[str, Any]]) -> List[str]:
        """Use Gemini AI to determine relevant categories for a podcast"""
        try:
            # Prepare podcast information
            title = podcast.get('title', '')
            description = podcast.get('description', '')
            publisher = podcast.get('publisher', '')
            
            # Try to get more detailed description from ListenNotes if available
            original_description = description
            if podcast.get('listennotes_id'):
                ln_data = await self.fetch_podcast_details_from_listennotes(podcast['listennotes_id'])
                if ln_data and ln_data.get('description'):
                    description = ln_data['description']
            
            # If description is too short or generic, try web search
            if len(description) < 50 or not description or description == original_description:
                logger.info(f"Description too short for '{title}', searching web for more info")
                web_info = await self.search_web_for_podcast_info(title, publisher)
                if web_info:
                    description = f"{description}\n\nAdditional Information from Web:\n{web_info}"
            
            # If still no useful information, try with minimal data
            if not description and not title:
                logger.warning(f"No description or title for podcast {podcast['id']}")
                return []
            
            # If we have only title, enhance the prompt
            if not description or len(description) < 20:
                logger.info(f"Using enhanced prompt for minimal data podcast: {title}")
                description = f"A podcast titled '{title}' by {publisher or 'unknown publisher'}. Limited information available."
            
            # Prepare categories for prompt
            category_list = []
            for cat in categories:
                cat_info = f"{cat['display_name']}"
                if cat.get('description'):
                    cat_info += f" - {cat['description']}"
                category_list.append(cat_info)
            
            # Create prompt for Gemini
            prompt = f"""
You are a podcast categorization expert. Based on the podcast information below, select the most relevant categories from the provided list.

Podcast Information:
Title: {title}
Publisher: {publisher}
Description: {description}

Available Categories:
{json.dumps(category_list, indent=2)}

Instructions:
1. Analyze the podcast's content, theme, and target audience
2. Select 1-3 most relevant categories (prefer fewer, highly relevant categories over many loosely related ones)
3. Return ONLY a JSON array of category display names that match exactly from the list above
4. If information is limited, make your best educated guess based on the title and any available context
5. Only return an empty array [] if absolutely no category could possibly fit

Example response: ["Technology", "Business & Finance"]

Response:
"""
            
            # Get response from Gemini
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Extract JSON array from response
            # Handle cases where Gemini might add extra text
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                selected_category_names = json.loads(json_str)
            else:
                logger.warning(f"Could not parse Gemini response: {response_text}")
                return []
            
            # Map display names back to category IDs
            category_ids = []
            for cat in categories:
                if cat['display_name'] in selected_category_names:
                    category_ids.append(cat['id'])
            
            logger.info(f"Categorized '{title}' into categories: {selected_category_names}")
            return category_ids
            
        except Exception as e:
            logger.error(f"Error categorizing podcast with Gemini: {e}")
            return []
    
    async def save_category_mappings(self, podcast_id: str, category_ids: List[str]) -> bool:
        """Save category mappings for a podcast"""
        if not category_ids:
            return False
        
        try:
            # Create mapping records
            mappings = [
                {'podcast_id': podcast_id, 'category_id': category_id}
                for category_id in category_ids
            ]
            
            # Insert mappings
            result = self.supabase.table('podcast_category_mappings') \
                .insert(mappings) \
                .execute()
            
            if result.data:
                logger.info(f"Saved {len(category_ids)} category mappings for podcast {podcast_id}")
                return True
            else:
                logger.error(f"Failed to save category mappings for podcast {podcast_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving category mappings: {e}")
            return False
    
    async def categorize_uncategorized_podcasts(self, batch_size: int = 10) -> Dict[str, int]:
        """Main function to categorize uncategorized podcasts"""
        try:
            # Get categories
            categories = await self.get_all_categories()
            if not categories:
                logger.error("No categories found in database")
                return {"processed": 0, "categorized": 0, "failed": 0}
            
            # Get uncategorized podcasts
            uncategorized_podcasts = await self.get_uncategorized_podcasts(limit=batch_size)
            if not uncategorized_podcasts:
                logger.info("No uncategorized podcasts found")
                return {"processed": 0, "categorized": 0, "failed": 0}
            
            logger.info(f"Found {len(uncategorized_podcasts)} uncategorized podcasts")
            
            processed = 0
            categorized = 0
            failed = 0
            
            for podcast in uncategorized_podcasts:
                processed += 1
                
                try:
                    # Categorize with Gemini
                    category_ids = await self.categorize_podcast_with_gemini(podcast, categories)
                    
                    if category_ids:
                        # Save mappings
                        success = await self.save_category_mappings(podcast['id'], category_ids)
                        if success:
                            categorized += 1
                        else:
                            failed += 1
                    else:
                        logger.warning(f"No categories identified for podcast: {podcast['title']}")
                        
                        # Try to add to a default "Uncategorized" or "Other" category if it exists
                        uncategorized_cat = next((cat for cat in categories if cat['name'].lower() in ['uncategorized', 'other', 'general']), None)
                        if uncategorized_cat:
                            logger.info(f"Adding to '{uncategorized_cat['display_name']}' category as fallback")
                            success = await self.save_category_mappings(podcast['id'], [uncategorized_cat['id']])
                            if success:
                                categorized += 1
                            else:
                                failed += 1
                        else:
                            failed += 1
                    
                    # Add a small delay to avoid rate limiting
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error processing podcast {podcast['id']}: {e}")
                    failed += 1
            
            stats = {
                "processed": processed,
                "categorized": categorized,
                "failed": failed
            }
            
            logger.info(f"Categorization complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error in categorization process: {e}")
            return {"processed": 0, "categorized": 0, "failed": 0}