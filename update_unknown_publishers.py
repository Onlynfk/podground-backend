"""
Update podcasts with 'Unknown Publisher' to use owner's name
"""
import asyncio
import logging
from supabase_client import SupabaseClient
from user_profile_service import UserProfileService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def update_unknown_publishers():
    """Update all podcasts with 'Unknown Publisher' to use owner's name"""
    try:
        supabase_client = SupabaseClient()
        profile_service = UserProfileService()

        # Get all podcasts with 'Unknown Publisher'
        result = supabase_client.service_client.table("podcasts").select(
            "id, listennotes_id, title, publisher"
        ).eq("publisher", "Unknown Publisher").execute()

        if not result.data:
            logger.info("No podcasts found with 'Unknown Publisher'")
            return

        logger.info(f"Found {len(result.data)} podcasts with 'Unknown Publisher'")
        updated_count = 0
        skipped_count = 0

        for podcast in result.data:
            podcast_id = podcast["id"]
            listennotes_id = podcast["listennotes_id"]
            title = podcast["title"]

            try:
                # Check if podcast is claimed
                claim_result = supabase_client.service_client.table("podcast_claims").select(
                    "user_id"
                ).eq("listennotes_id", listennotes_id).eq("is_verified", True).eq("claim_status", "verified").execute()

                if claim_result.data and len(claim_result.data) > 0:
                    user_id = claim_result.data[0]["user_id"]

                    # Get owner's profile
                    owner_profile = await profile_service.get_user_profile(user_id)

                    if owner_profile and owner_profile.get("name"):
                        owner_name = owner_profile["name"]

                        # Update podcast publisher
                        update_result = supabase_client.service_client.table("podcasts").update({
                            "publisher": owner_name
                        }).eq("id", podcast_id).execute()

                        if update_result.data:
                            logger.info(f"✅ Updated podcast '{title}' publisher to '{owner_name}'")
                            updated_count += 1
                        else:
                            logger.warning(f"Failed to update podcast '{title}'")
                            skipped_count += 1
                    else:
                        # Set to empty string if we can't get owner name
                        update_result = supabase_client.service_client.table("podcasts").update({
                            "publisher": ""
                        }).eq("id", podcast_id).execute()

                        if update_result.data:
                            logger.info(f"✅ Updated podcast '{title}' publisher to empty string (no owner name)")
                            updated_count += 1
                        else:
                            skipped_count += 1
                else:
                    # Not claimed - set to empty string
                    update_result = supabase_client.service_client.table("podcasts").update({
                        "publisher": ""
                    }).eq("id", podcast_id).execute()

                    if update_result.data:
                        logger.info(f"✅ Updated unclaimed podcast '{title}' publisher to empty string")
                        updated_count += 1
                    else:
                        skipped_count += 1

            except Exception as e:
                logger.error(f"Error updating podcast '{title}' (ID: {podcast_id}): {e}")
                skipped_count += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"Update complete!")
        logger.info(f"Updated: {updated_count}")
        logger.info(f"Skipped: {skipped_count}")
        logger.info(f"{'='*60}")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(update_unknown_publishers())
