"""
Background service to import verified claimed podcasts into the main podcasts table
"""
import os
import logging
from typing import List, Dict, Any
from supabase import Client

logger = logging.getLogger(__name__)

class ClaimedPodcastImportService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
        
    async def get_verified_claims_not_imported(self) -> List[Dict[str, Any]]:
        """Get verified podcast claims that haven't been imported OR need full data fetching"""
        try:
            # Get all verified claims
            claims_result = self.supabase.table('podcast_claims') \
                .select('*') \
                .eq('is_verified', True) \
                .eq('claim_status', 'verified') \
                .execute()

            if not claims_result.data:
                logger.info("No verified claims found")
                return []

            # Check which ones are not in the main podcasts table OR need full data
            unimported_claims = []

            for claim in claims_result.data:
                listennotes_id = claim.get('listennotes_id')
                if not listennotes_id:
                    logger.warning(f"Claim {claim['id']} has no listennotes_id")
                    continue

                # Check if this podcast already exists in main table
                existing_result = self.supabase.table('podcasts') \
                    .select('id, has_full_data') \
                    .eq('listennotes_id', listennotes_id) \
                    .execute()

                if not existing_result.data:
                    # Not imported yet
                    unimported_claims.append(claim)
                    logger.info(f"Found unimported claim: {claim.get('podcast_title')} (ID: {listennotes_id})")
                else:
                    # Check if it needs full data fetch
                    has_full_data = existing_result.data[0].get('has_full_data', False)
                    if not has_full_data:
                        # Missing full data, needs retry
                        unimported_claims.append(claim)
                        logger.info(f"Found claim with incomplete data, will retry: {claim.get('podcast_title')} (ID: {listennotes_id})")
            
            return unimported_claims
            
        except Exception as e:
            logger.error(f"Error getting verified claims not imported: {e}")
            return []
    
    async def import_claimed_podcast(self, claim: Dict[str, Any]) -> bool:
        """Import a single claimed podcast into the main podcasts table"""
        try:
            listennotes_id = claim.get("listennotes_id")
            podcast_title = claim.get("podcast_title")
            
            if not listennotes_id or not podcast_title:
                logger.warning(f"Missing required data for podcast import: listennotes_id={listennotes_id}, title={podcast_title}")
                return False
            
            # Check if podcast already exists (and whether it has full data)
            existing_check = self.supabase.table("podcasts").select("id, has_full_data").eq("listennotes_id", listennotes_id).execute()
            existing_podcast = existing_check.data[0] if existing_check.data else None
            has_full_data = existing_podcast and existing_podcast.get('has_full_data', False)

            if existing_podcast and has_full_data:
                # Already has full data, skip
                logger.info(f"Podcast '{podcast_title}' already has full data, skipping")
                return True

            # Try to get full podcast data from ListenNotes API
            insert_data = None
            
            try:
                if self.listennotes_api_key:
                    from listennotes_client import ListenNotesClient

                    ln_client = ListenNotesClient(self.listennotes_api_key)
                    podcast_result = ln_client.get_podcast_by_id(listennotes_id)

                    if podcast_result and podcast_result.get('success') and podcast_result.get('data'):
                        podcast_data = podcast_result['data']
                        # Insert with full data from ListenNotes
                        insert_data = {
                            'listennotes_id': listennotes_id,
                            'title': podcast_data.get('title', podcast_title),
                            'description': podcast_data.get('description', ''),
                            'publisher': podcast_data.get('publisher', ''),
                            'language': podcast_data.get('language', 'en'),
                            'image_url': podcast_data.get('image', ''),
                            'thumbnail_url': podcast_data.get('thumbnail', ''),
                            'rss_url': podcast_data.get('rss', ''),
                            'total_episodes': podcast_data.get('total_episodes', 0),
                            'explicit_content': podcast_data.get('explicit_content', False),
                            'has_full_data': True,
                            'created_at': 'now()',
                            'updated_at': 'now()'
                        }
                        logger.info(f"Fetched full data from ListenNotes for '{podcast_title}'")
                    else:
                        logger.warning(f"ListenNotes returned no data for '{podcast_title}'")
                        
            except Exception as ln_error:
                logger.warning(f"Could not fetch full data from ListenNotes for '{podcast_title}': {ln_error}")
            
            # Fallback to minimal data from claim if ListenNotes failed
            if not insert_data:
                insert_data = {
                    'listennotes_id': listennotes_id,
                    'title': podcast_title,
                    'description': '',
                    'publisher': '',
                    'language': 'en',
                    'image_url': '',
                    'thumbnail_url': '',
                    'rss_url': '',
                    'total_episodes': 0,
                    'explicit_content': False,
                    'has_full_data': False,
                    'created_at': 'now()',
                    'updated_at': 'now()'
                }
                logger.warning(f"Failed to fetch full data, using placeholder for '{podcast_title}' (will retry later)")

            # Insert or update podcast
            if existing_podcast:
                # Update existing podcast with new data
                podcast_id = existing_podcast['id']
                update_data = {k: v for k, v in insert_data.items() if k not in ['created_at']}
                update_data['updated_at'] = 'now()'
                result = self.supabase.table("podcasts").update(update_data).eq("id", podcast_id).execute()
                logger.info(f"Updated podcast '{podcast_title}' with {'full' if insert_data.get('has_full_data') else 'placeholder'} data")
            else:
                # Insert new podcast
                result = self.supabase.table("podcasts").insert(insert_data).execute()
                logger.info(f"Inserted new podcast '{podcast_title}' with {'full' if insert_data.get('has_full_data') else 'placeholder'} data")
                if result.data:
                    podcast_id = result.data[0]['id']

            if not result.data:
                logger.error(f"Failed to insert/update claimed podcast '{podcast_title}' into main table")
                return False

            # Try to add category mapping using first genre_id from ListenNotes
            try:
                if 'podcast_data' in locals() and podcast_data and 'genre_ids' in podcast_data:
                    genre_ids = podcast_data.get('genre_ids', [])

                    if genre_ids and len(genre_ids) > 0:
                        # Take only the first genre_id
                        first_genre_id = genre_ids[0]
                        logger.info(f"Mapping first genre_id {first_genre_id} to PodGround category")

                        # Look up PodGround category from genre mapping table
                        genre_mapping_result = self.supabase.table('category_genre') \
                            .select('category_id') \
                            .eq('genre_id', first_genre_id) \
                            .limit(1) \
                            .execute()

                        if genre_mapping_result.data:
                            category_id = genre_mapping_result.data[0]['category_id']

                            # Add the category mapping to the junction table
                            mapping = {'podcast_id': podcast_id, 'category_id': category_id}

                            mappings_result = self.supabase.table('podcast_category_mappings') \
                                .insert([mapping]) \
                                .execute()

                            if mappings_result.data:
                                logger.info(f"Mapped genre_id {first_genre_id} to category {category_id} for claimed podcast")
                            else:
                                logger.warning(f"Failed to add category mapping for claimed podcast")
                        else:
                            logger.warning(f"No PodGround category mapping found for genre_id {first_genre_id}")
                    else:
                        logger.info("No genre_ids available from ListenNotes for this podcast")

            except Exception as cat_error:
                logger.warning(f"Could not add category mapping for claimed podcast: {cat_error}")

            return True
                
        except Exception as e:
            logger.error(f"Error importing claimed podcast: {e}")
            return False
    
    async def process_unimported_claims(self, batch_size: int = 10) -> Dict[str, int]:
        """Main function to process unimported claimed podcasts"""
        try:
            # Get unimported claims
            unimported_claims = await self.get_verified_claims_not_imported()
            
            if not unimported_claims:
                logger.info("No unimported claims found")
                return {"processed": 0, "imported": 0, "failed": 0}
            
            logger.info(f"Found {len(unimported_claims)} unimported claims")
            
            # Process in batches
            claims_to_process = unimported_claims[:batch_size]
            
            processed = 0
            imported = 0
            failed = 0
            
            for claim in claims_to_process:
                processed += 1
                
                try:
                    success = await self.import_claimed_podcast(claim)
                    
                    if success:
                        imported += 1
                        logger.info(f"✓ Imported: {claim.get('podcast_title')}")
                    else:
                        failed += 1
                        logger.error(f"✗ Failed to import: {claim.get('podcast_title')}")
                    
                    # Small delay to avoid overwhelming the API
                    import asyncio
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error processing claim {claim.get('id')}: {e}")
                    failed += 1
            
            stats = {
                "processed": processed,
                "imported": imported,
                "failed": failed,
                "remaining": len(unimported_claims) - processed
            }
            
            logger.info(f"Import complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error in process_unimported_claims: {e}")
            return {"processed": 0, "imported": 0, "failed": 0, "remaining": 0}