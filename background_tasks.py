import os
import logging
from typing import Dict
from supabase_client import SupabaseClient
from customerio_client import CustomerIOClient
from media_service import MediaService
from events_notifications import events_notification_service

logger = logging.getLogger(__name__)

# Initialize clients
supabase_client = SupabaseClient()
customerio_client = CustomerIOClient()

def get_magic_link_expiry_seconds() -> int:
    """Get magic link expiry time in seconds from environment variable"""
    hours = int(os.getenv("MAGIC_LINK_EXPIRY_HOURS", "24"))
    return hours * 3600  # Convert hours to seconds

def get_verification_code_expiry_hours() -> int:
    """Get verification code expiry time in hours from environment variable"""
    return int(os.getenv("VERIFICATION_CODE_EXPIRY_HOURS", "24"))

def get_user_display_name(user_id: str, fallback_email: str = "") -> str:
    """Get user's display name from Supabase, with email fallback"""
    try:
        if user_id and supabase_client.service_client:
            user_data = supabase_client.service_client.auth.admin.get_user_by_id(user_id)
            if user_data and hasattr(user_data, 'user') and user_data.user.user_metadata:
                first_name = user_data.user.user_metadata.get('first_name', '')
                last_name = user_data.user.user_metadata.get('last_name', '')
                user_name = f"{first_name} {last_name}".strip()
                if user_name:
                    return user_name
            # Try to get email from user data if not provided
            if not fallback_email and hasattr(user_data, 'user') and user_data.user.email:
                fallback_email = user_data.user.email
    except Exception as e:
        logger.warning(f"Could not get user display name: {str(e)}")
    
    # Fallback to email prefix
    return fallback_email.split('@')[0] if fallback_email else "User"

def get_user_email_by_id(user_id: str) -> str:
    """Get user's email from Supabase by user_id"""
    try:
        if user_id and supabase_client.service_client:
            user_data = supabase_client.service_client.auth.admin.get_user_by_id(user_id)
            if user_data and hasattr(user_data, 'user') and user_data.user.email:
                return user_data.user.email
    except Exception as e:
        logger.warning(f"Could not get user email for user_id {user_id}: {str(e)}")
    
    return ""

async def send_signup_reminders() -> Dict:
    """Send signup reminders to users who haven't logged in within 24 hours"""
    logger.info("Starting signup reminders background task")
    
    try:
        # Get users who need reminders from Supabase
        users_result = supabase_client.get_users_needing_reminder(hours_since_signup=24)
        
        if not users_result["success"]:
            return {
                "success": False,
                "error": f"Failed to get users needing reminder: {users_result.get('error')}"
            }
        
        users_needing_reminder = users_result.get("data", [])
        reminder_count = 0
        errors = []
        
        for user in users_needing_reminder:
            try:
                # Generate new magic link with 24-hour expiry for reminder
                backend_url = "http://localhost:8000"  # Your API URL
                redirect_url = f"{backend_url}/auth/callback"
                
                magic_link_result = supabase_client.generate_magic_link(
                    user["email"],
                    redirect_url,
                    expiry_seconds=get_magic_link_expiry_seconds()
                )
                
                magic_link_url = ""
                if magic_link_result["success"]:
                    magic_link_data = magic_link_result.get("data")
                    if magic_link_data and hasattr(magic_link_data, 'properties'):
                        magic_link_url = magic_link_data.properties.action_link
                else:
                    logger.warning(f"Failed to generate reminder magic link for {user['email']}: {magic_link_result.get('error')}")
                    continue  # Skip this user if we can't generate a magic link
                
                # Send reminder email with magic link
                result = customerio_client.send_signup_reminder_transactional(
                    email=user["email"],
                    name=user.get("name", ""),
                    magic_link_url=magic_link_url
                )
                
                if result["success"]:
                    # Mark reminder as sent in Supabase
                    mark_result = supabase_client.mark_reminder_sent(user["user_id"])
                    if mark_result["success"]:
                        reminder_count += 1
                        logger.info(f"Sent signup reminder to {user['email']}")
                    else:
                        error_msg = f"Sent email to {user['email']} but failed to mark as sent: {mark_result.get('error')}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                else:
                    error_msg = f"Failed to send reminder to {user['email']}: {result.get('error')}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                error_msg = f"Error processing reminder for {user['email']}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Signup reminders task completed: {reminder_count} sent, {len(users_needing_reminder)} checked")
        
        return {
            "success": True,
            "reminders_sent": reminder_count,
            "users_checked": len(users_needing_reminder),
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Signup reminders task error: {str(e)}")
        return {"success": False, "error": str(e)}

async def send_podcast_claim_reminders() -> Dict:
    """Send podcast claim login reminders to users for unverified claims after 24 hours"""
    logger.info("Starting podcast claim reminders background task")
    
    try:
        # Get claims that need reminders
        claims_result = supabase_client.get_podcast_claims_needing_reminder(hours_since_created=24)
        
        if not claims_result["success"]:
            return {
                "success": False,
                "error": f"Failed to get claims needing reminder: {claims_result.get('error')}"
            }
        
        claims_needing_reminder = claims_result.get("data", [])
        reminder_count = 0
        errors = []
        
        for claim in claims_needing_reminder:
            try:
                # Get user's email from their user_id
                user_email = get_user_email_by_id(claim["user_id"])
                if not user_email:
                    error_msg = f"Could not get email for user {claim['user_id']} for claim {claim['id']}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    continue
                
                # Generate magic link for user to login and restart claim process
                backend_url = "http://localhost:8000"  # Your API URL
                redirect_url = f"{backend_url}/auth/callback"
                
                magic_link_result = supabase_client.generate_magic_link(
                    user_email,
                    redirect_url,
                    expiry_seconds=get_magic_link_expiry_seconds()
                )
                
                magic_link_url = ""
                if magic_link_result["success"]:
                    magic_link_data = magic_link_result.get("data")
                    if magic_link_data and hasattr(magic_link_data, 'properties'):
                        magic_link_url = magic_link_data.properties.action_link
                else:
                    error_msg = f"Failed to generate magic link for user {user_email} for claim {claim['id']}: {magic_link_result.get('error')}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    continue
                
                # Get user's display name for email
                user_name = get_user_display_name(claim["user_id"], user_email)
                
                # Send reminder email to user with magic link to restart claim process
                email_result = customerio_client.send_podcast_claim_login_reminder_transactional(
                    email=user_email,
                    name=user_name,
                    podcast_title=claim["podcast_title"],
                    magic_link_url=magic_link_url
                )
                
                if email_result["success"]:
                    # Mark reminder as sent in Supabase
                    mark_result = supabase_client.mark_podcast_claim_reminder_sent(claim["id"])
                    if mark_result["success"]:
                        reminder_count += 1
                        logger.info(f"Sent podcast claim login reminder for '{claim['podcast_title']}' to user {user_email}")
                    else:
                        error_msg = f"Sent reminder email for claim {claim['id']} but failed to mark as sent: {mark_result.get('error')}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                else:
                    error_msg = f"Failed to send reminder for claim {claim['id']}: {email_result.get('error')}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                error_msg = f"Error processing reminder for claim {claim['id']}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Podcast claim reminders task completed: {reminder_count} sent, {len(claims_needing_reminder)} checked")
        
        return {
            "success": True,
            "reminders_sent": reminder_count,
            "claims_checked": len(claims_needing_reminder),
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Podcast claim reminders task error: {str(e)}")
        return {"success": False, "error": str(e)}

async def sync_signup_confirmations() -> Dict:
    """Sync confirmed signups to Customer.io"""
    logger.info("Starting signup confirmations sync background task")
    
    try:
        # Get users who have confirmed signup but haven't been synced to Customer.io
        users_result = supabase_client.get_users_needing_confirmation_sync()
        
        if not users_result["success"]:
            return {
                "success": False,
                "error": f"Failed to get users needing confirmation sync: {users_result.get('error')}"
            }
        
        users_needing_sync = users_result.get("data", [])
        sync_count = 0
        errors = []
        
        for user in users_needing_sync:
            try:
                # Mark signup as confirmed in Customer.io
                result = customerio_client.mark_signup_confirmed(
                    email=user["email"],
                    name=user.get("name", "")
                )
                
                if result["success"]:
                    # Mark as synced in Supabase
                    mark_result = supabase_client.mark_confirmation_synced_to_customerio(user["user_id"])
                    if mark_result["success"]:
                        sync_count += 1
                        logger.info(f"Synced signup confirmation to Customer.io for {user['email']}")
                    else:
                        error_msg = f"Updated Customer.io for {user['email']} but failed to mark as synced: {mark_result.get('error')}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                else:
                    error_msg = f"Failed to sync confirmation to Customer.io for {user['email']}: {result.get('error')}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                error_msg = f"Error processing confirmation sync for {user['email']}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Signup confirmations sync task completed: {sync_count} synced, {len(users_needing_sync)} checked")
        
        return {
            "success": True,
            "confirmations_synced": sync_count,
            "users_checked": len(users_needing_sync),
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Signup confirmations sync task error: {str(e)}")
        return {"success": False, "error": str(e)}

async def sync_failed_waitlist_entries() -> Dict:
    """Retry syncing failed waitlist entries to Customer.io"""
    logger.info("Starting failed waitlist sync background task")
    
    try:
        synced_count = 0
        errors = []
        
        # Process regular waitlist entries
        waitlist_result = supabase_client.get_unsynced_waitlist_entries("waitlist_emails", retry_limit=1000)
        
        if waitlist_result["success"]:
            waitlist_entries = waitlist_result.get("data", [])
            logger.info(f"Found {len(waitlist_entries)} unsynced waitlist entries")
            
            for entry in waitlist_entries:
                try:
                    # Try to sync to Customer.io
                    result = customerio_client.add_contact(
                        email=entry["email"],
                        first_name=entry.get("first_name", ""),
                        last_name=entry.get("last_name", ""),
                        variant=entry.get("variant", "A")
                    )
                    
                    if result["success"]:
                        # Mark as synced
                        supabase_client.update_customerio_sync_status("waitlist_emails", entry["id"], "synced")
                        synced_count += 1
                        logger.info(f"Successfully synced waitlist entry {entry['email']} to Customer.io")
                    else:
                        # Mark as failed and increment attempts
                        supabase_client.update_customerio_sync_status("waitlist_emails", entry["id"], "failed", increment_attempts=True)
                        error_msg = f"Failed to sync {entry['email']}: {result.get('error')}"
                        errors.append(error_msg)
                        logger.warning(error_msg)
                        
                except Exception as e:
                    # Mark as failed and increment attempts
                    supabase_client.update_customerio_sync_status("waitlist_emails", entry["id"], "failed", increment_attempts=True)
                    error_msg = f"Error syncing {entry['email']}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        # Process microgrant waitlist entries
        microgrant_result = supabase_client.get_unsynced_waitlist_entries("microgrant_waitlist_emails", retry_limit=1000)
        
        if microgrant_result["success"]:
            microgrant_entries = microgrant_result.get("data", [])
            logger.info(f"Found {len(microgrant_entries)} unsynced microgrant waitlist entries")
            
            for entry in microgrant_entries:
                try:
                    # Try to sync to Customer.io
                    result = customerio_client.add_microgrant_contact(
                        email=entry["email"],
                        first_name=entry.get("first_name", ""),
                        last_name=entry.get("last_name", "")
                    )
                    
                    if result["success"]:
                        # Mark as synced
                        supabase_client.update_customerio_sync_status("microgrant_waitlist_emails", entry["id"], "synced")
                        synced_count += 1
                        logger.info(f"Successfully synced microgrant entry {entry['email']} to Customer.io")
                    else:
                        # Mark as failed and increment attempts
                        supabase_client.update_customerio_sync_status("microgrant_waitlist_emails", entry["id"], "failed", increment_attempts=True)
                        error_msg = f"Failed to sync microgrant {entry['email']}: {result.get('error')}"
                        errors.append(error_msg)
                        logger.warning(error_msg)
                        
                except Exception as e:
                    # Mark as failed and increment attempts
                    supabase_client.update_customerio_sync_status("microgrant_waitlist_emails", entry["id"], "failed", increment_attempts=True)
                    error_msg = f"Error syncing microgrant {entry['email']}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        logger.info(f"Failed waitlist sync task completed: {synced_count} synced, {len(errors)} errors")
        
        return {
            "success": True,
            "synced_count": synced_count,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Failed waitlist sync task error: {str(e)}")
        return {"success": False, "error": str(e)}


async def process_event_reminders() -> Dict:
    """Process pending event reminders and send notifications"""
    logger.info("Starting event reminders processing task")
    
    try:
        result = await events_notification_service.process_pending_reminders()
        
        if result['success']:
            logger.info(f"Event reminders processed: {result['processed']} sent, {result['failed']} failed")
        else:
            logger.error(f"Event reminders processing failed: {result['error']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Event reminders processing error: {str(e)}")
        return {"success": False, "error": str(e)}

async def categorize_uncategorized_podcasts() -> Dict:
    """Categorize podcasts that don't have any category mappings using Gemini AI"""
    logger.info("Starting podcast categorization task")
    
    try:
        from podcast_categorization_service import PodcastCategorizationService
        
        # Initialize the categorization service with service client (bypasses RLS)
        categorization_service = PodcastCategorizationService(supabase_client.service_client)
        
        # Process a batch of uncategorized podcasts
        result = await categorization_service.categorize_uncategorized_podcasts(batch_size=10)
        
        logger.info(f"Podcast categorization completed: {result['processed']} processed, {result['categorized']} categorized, {result['failed']} failed")
        
        return {
            "success": True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Podcast categorization error: {str(e)}")
        return {"success": False, "error": str(e), "processed": 0, "categorized": 0, "failed": 0}

async def import_claimed_podcasts() -> Dict:
    """Import verified claimed podcasts into the main podcasts table"""
    logger.info("Starting claimed podcasts import task")
    
    try:
        from claimed_podcast_import_service import ClaimedPodcastImportService
        
        # Initialize the import service with service client (bypasses RLS)
        import_service = ClaimedPodcastImportService(supabase_client.service_client)
        
        # Process a batch of unimported claims
        result = await import_service.process_unimported_claims(batch_size=20)
        
        logger.info(f"Claimed podcasts import completed: {result['processed']} processed, {result['imported']} imported, {result['failed']} failed, {result.get('remaining', 0)} remaining")
        
        return {
            "success": True,
            **result
        }
        
    except Exception as e:
        logger.error(f"Claimed podcasts import error: {str(e)}")
        return {"success": False, "error": str(e), "processed": 0, "imported": 0, "failed": 0, "remaining": 0}

async def refresh_featured_podcast_episodes() -> Dict:
    """
    Background job to refresh latest episodes for featured podcasts with expired TTL cache.
    Runs periodically to ensure featured podcasts always show fresh episodes.
    """
    try:
        from podcast_service import PodcastDiscoveryService
        from datetime import datetime, timezone, timedelta
        
        logger.info("Starting featured podcast episode cache refresh...")
        
        # Initialize podcast service
        podcast_service = PodcastDiscoveryService(supabase_client.service_client)
        
        # Get TTL from environment (default: 6 hours)
        ttl_hours = int(os.getenv('LATEST_EPISODE_TTL_HOURS', '6'))
        ttl_threshold = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        
        # Find featured podcasts with expired cache or no cache
        try:
            # Try to query with latest_episode_updated_at column
            featured_result = supabase_client.service_client.table('podcasts') \
                .select('id, title, listennotes_id, latest_episode_id, latest_episode_updated_at') \
                .eq('is_featured', True) \
                .execute()
        except Exception as e:
            if 'latest_episode_updated_at' in str(e):
                # Column doesn't exist yet, query without it
                logger.info("TTL column not available, refreshing all featured podcasts")
                featured_result = supabase_client.service_client.table('podcasts') \
                    .select('id, title, listennotes_id, latest_episode_id') \
                    .eq('is_featured', True) \
                    .execute()
            else:
                raise
        
        if not featured_result.data:
            logger.info("No featured podcasts found")
            return {"success": True, "processed": 0, "refreshed": 0, "skipped": 0, "failed": 0}
        
        featured_podcasts = featured_result.data
        total_count = len(featured_podcasts)
        refreshed_count = 0
        skipped_count = 0
        failed_count = 0
        
        logger.info(f"Found {total_count} featured podcasts to check for cache refresh")
        
        for podcast in featured_podcasts:
            podcast_id = podcast['id']
            title = podcast['title']
            listennotes_id = podcast['listennotes_id']
            latest_episode_updated_at = podcast.get('latest_episode_updated_at')
            
            try:
                # Check if cache refresh is needed
                needs_refresh = True
                
                if latest_episode_updated_at:
                    # TTL-based check
                    try:
                        updated_time = datetime.fromisoformat(latest_episode_updated_at.replace('Z', '+00:00'))
                        needs_refresh = updated_time < ttl_threshold
                        
                        if not needs_refresh:
                            logger.debug(f"Cache fresh for {title[:30]}... (updated {updated_time})")
                            skipped_count += 1
                            continue
                        else:
                            logger.info(f"Cache expired for {title[:30]}... (updated {updated_time})")
                    except Exception as e:
                        logger.warning(f"Error parsing timestamp for {title}: {e}")
                        needs_refresh = True
                else:
                    # No timestamp available, check if we have any latest_episode_id
                    if podcast.get('latest_episode_id'):
                        # We have an episode but no timestamp - skip refresh to avoid constant API calls
                        logger.debug(f"No TTL timestamp for {title[:30]}..., but has episode - skipping")
                        skipped_count += 1
                        continue
                    else:
                        logger.info(f"No cached episode for {title[:30]}... - needs refresh")
                
                # Refresh from API
                if not listennotes_id:
                    logger.warning(f"No ListenNotes ID for {title} - skipping")
                    failed_count += 1
                    continue
                
                logger.info(f"Refreshing {title[:30]}... from API")
                fresh_episode = await podcast_service._refresh_latest_episode_from_api(podcast_id, listennotes_id)
                
                if fresh_episode:
                    refreshed_count += 1
                    logger.info(f"✅ Refreshed {title[:30]}... -> {fresh_episode.get('title', '')[:30]}...")
                else:
                    failed_count += 1
                    logger.warning(f"❌ Failed to refresh {title[:30]}...")
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Error refreshing {title}: {e}")
        
        logger.info(f"Featured podcast cache refresh completed: {refreshed_count} refreshed, {skipped_count} skipped (fresh), {failed_count} failed")
        
        return {
            "success": True,
            "processed": total_count,
            "refreshed": refreshed_count,
            "skipped": skipped_count,
            "failed": failed_count
        }
        
    except Exception as e:
        logger.error(f"Featured podcast cache refresh error: {str(e)}")
        return {"success": False, "error": str(e), "processed": 0, "refreshed": 0, "skipped": 0, "failed": 0}

async def refresh_stale_podcast_episodes() -> Dict:
    """
    Background job to refresh latest episodes for ANY podcasts with very stale cache (24+ hours).
    This catches non-featured podcasts that users might access.
    """
    try:
        from podcast_service import PodcastDiscoveryService
        from datetime import datetime, timezone, timedelta
        
        logger.info("Starting stale podcast episode cache refresh...")
        
        # Initialize podcast service
        podcast_service = PodcastDiscoveryService(supabase_client.service_client)
        
        # Check for podcasts with very stale cache (24+ hours)
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        
        try:
            # Find podcasts with very old cache
            stale_result = supabase_client.service_client.table('podcasts') \
                .select('id, title, listennotes_id, latest_episode_updated_at') \
                .not_.is_('listennotes_id', None) \
                .not_.is_('latest_episode_updated_at', None) \
                .lt('latest_episode_updated_at', stale_threshold.isoformat()) \
                .limit(10) \
                .execute()
        except Exception as e:
            if 'latest_episode_updated_at' in str(e):
                logger.info("TTL column not available, skipping stale podcast refresh")
                return {"success": True, "processed": 0, "refreshed": 0, "skipped": 0, "failed": 0}
            else:
                raise
        
        if not stale_result.data:
            logger.info("No stale podcasts found")
            return {"success": True, "processed": 0, "refreshed": 0, "skipped": 0, "failed": 0}
        
        stale_podcasts = stale_result.data
        total_count = len(stale_podcasts)
        refreshed_count = 0
        failed_count = 0
        
        logger.info(f"Found {total_count} stale podcasts to refresh")
        
        for podcast in stale_podcasts:
            podcast_id = podcast['id']
            title = podcast['title']
            listennotes_id = podcast['listennotes_id']
            
            try:
                logger.info(f"Refreshing stale podcast {title[:30]}...")
                fresh_episode = await podcast_service._refresh_latest_episode_from_api(podcast_id, listennotes_id)
                
                if fresh_episode:
                    refreshed_count += 1
                    logger.info(f"✅ Refreshed stale podcast {title[:30]}...")
                else:
                    failed_count += 1
                    logger.warning(f"❌ Failed to refresh stale podcast {title[:30]}...")
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Error refreshing stale podcast {title}: {e}")
        
        logger.info(f"Stale podcast cache refresh completed: {refreshed_count} refreshed, {failed_count} failed")
        
        return {
            "success": True,
            "processed": total_count,
            "refreshed": refreshed_count,
            "skipped": 0,
            "failed": failed_count
        }
        
    except Exception as e:
        logger.error(f"Stale podcast cache refresh error: {str(e)}")
        return {"success": False, "error": str(e), "processed": 0, "refreshed": 0, "skipped": 0, "failed": 0}