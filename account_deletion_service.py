"""
Account Deletion Service
Handles complete account deletion with logging and cascading deletions across all tables
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class AccountDeletionService:
    def __init__(self):
        self.supabase_client = SupabaseClient()
        self.supabase = self.supabase_client.service_client

    async def delete_user_account(
        self,
        user_id: str,
        deletion_reason: Optional[str] = None,
        deleted_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Delete a user account and all associated data

        Args:
            user_id: User ID to delete
            deletion_reason: Optional reason for deletion
            deleted_by: User ID of admin who initiated deletion (None if self-delete)
            ip_address: IP address of deletion request
            user_agent: User agent of deletion request

        Returns:
            Dictionary with success status and deletion summary
        """
        try:
            # 1. Get user data for logging
            user_data = await self._get_user_snapshot(user_id)
            if not user_data:
                return {
                    'success': False,
                    'error': 'User not found'
                }

            # 2. Count all records to be deleted
            deletion_counts = await self._count_user_records(user_id)

            # 3. Log the deletion BEFORE deleting anything (optional - may not exist if migration not run)
            log_entry = None
            try:
                log_entry = await self._create_deletion_log(
                    user_id=user_id,
                    user_data=user_data,
                    deletion_counts=deletion_counts,
                    deletion_reason=deletion_reason,
                    deleted_by=deleted_by,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            except Exception as e:
                logger.warning(f"Could not create deletion log (table may not exist): {e}")

            # 4. Delete all user data manually FIRST (to avoid cascade issues)
            deletion_results = await self._delete_all_user_data(user_id)

            # 5. Clear foreign keys that don't have CASCADE
            await self._clear_non_cascade_foreign_keys(user_id)

            # 6. Delete from auth.users LAST (after all data is gone)
            auth_deletion_success = False
            try:
                # Using Supabase Admin API to delete auth user
                # All data should be deleted by now, so this should work
                auth_result = self.supabase.auth.admin.delete_user(user_id, should_soft_delete=False)
                auth_deletion_success = True
                logger.info(f"Successfully deleted auth user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete auth user {user_id}: {e}")
                logger.error(f"Auth deletion error type: {type(e).__name__}")
                logger.warning(
                    f"Auth user deletion failed, but all user data was deleted. "
                    f"The auth user may still exist in Supabase."
                )

            deletion_results['auth_user'] = auth_deletion_success

            return {
                'success': True,
                'user_id': user_id,
                'deletion_log_id': log_entry.get('id') if log_entry else None,
                'deleted_counts': deletion_counts,
                'deletion_summary': deletion_results,
                'auth_deletion_failed': not auth_deletion_success
            }

        except Exception as e:
            logger.error(f"Error deleting user account {user_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _get_user_snapshot(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get complete snapshot of user data for logging"""
        try:
            # Get user from auth.users
            auth_user = None
            try:
                auth_user = self.supabase.auth.admin.get_user_by_id(user_id)
            except Exception as e:
                logger.warning(f"Could not fetch auth user: {e}")

            # Get user profile
            profile = None
            try:
                profile_result = self.supabase.table('user_profiles').select('*').eq(
                    'user_id', user_id
                ).execute()
                if profile_result.data:
                    profile = profile_result.data[0]
            except Exception as e:
                logger.warning(f"Could not fetch user profile: {e}")

            # Compile snapshot
            snapshot = {
                'user_id': user_id,
                'email': auth_user.user.email if auth_user else None,
                'username': profile.get('username') if profile else None,
                'first_name': profile.get('first_name') if profile else None,
                'last_name': profile.get('last_name') if profile else None,
                'account_created_at': auth_user.user.created_at.isoformat() if (auth_user and auth_user.user.created_at) else None,
                'profile_data': profile
            }

            return snapshot

        except Exception as e:
            logger.error(f"Error getting user snapshot: {e}")
            return None

    async def _count_user_records(self, user_id: str) -> Dict[str, int]:
        """Count all records that will be deleted"""
        counts = {}

        tables_to_count = [
            # User profile and settings
            ('user_profiles', 'user_id'),
            ('user_notification_preferences', 'user_id'),
            ('user_privacy_settings', 'user_id'),

            # Social features
            ('posts', 'user_id'),
            ('post_likes', 'user_id'),
            ('post_comments', 'user_id'),
            ('comment_likes', 'user_id'),

            # Connections (both directions)
            ('user_connections', 'follower_id'),
            ('user_connections', 'following_id'),

            # Messages
            ('messages', 'sender_id'),
            ('message_reactions', 'user_id'),
            ('conversation_participants', 'user_id'),

            # Notifications
            ('notifications', 'user_id'),

            # Podcasts
            ('user_listening_progress', 'user_id'),
            ('user_podcast_follows', 'user_id'),
            ('podcast_claims', 'user_id'),

            # Resources
            ('resource_interactions', 'user_id'),

            # Tracking/Activity
            ('user_signup_tracking', 'user_id'),
            ('user_onboarding', 'id'),
            ('user_activity', 'user_id'),
        ]

        for table_name, column_name in tables_to_count:
            try:
                # Use the primary key column for counting (user_id for settings tables, id for others)
                pk_column = 'user_id' if table_name in ['user_notification_preferences', 'user_privacy_settings'] else 'id'
                result = self.supabase.table(table_name).select(
                    pk_column, count='exact'
                ).eq(column_name, user_id).execute()
                counts[table_name] = result.count or 0
            except Exception as e:
                logger.warning(f"Could not count {table_name}: {e}")
                counts[table_name] = 0

        return counts

    async def _clear_non_cascade_foreign_keys(self, user_id: str) -> None:
        """Clear foreign keys that reference auth.users without CASCADE"""
        try:
            # Clear events.host_user_id (ON DELETE SET NULL - but not automatic)
            self.supabase.table('events').update({'host_user_id': None}).eq('host_user_id', user_id).execute()
            logger.info(f"Cleared events.host_user_id for user {user_id}")
        except Exception as e:
            logger.warning(f"Could not clear events.host_user_id: {e}")

    async def _delete_all_user_data(self, user_id: str) -> Dict[str, bool]:
        """Delete all user data from all tables in correct order (manual cleanup/fallback)"""
        results = {}

        # Order matters - delete child records before parent records
        deletion_order = [
            # 1. Delete dependent records first
            ('message_reactions', 'user_id'),
            ('notifications', 'user_id'),
            ('notifications', 'related_user_id'),

            # 2. Delete likes and interactions
            ('comment_likes', 'user_id'),
            ('post_likes', 'user_id'),
            ('resource_interactions', 'user_id'),

            # 3. Delete comments
            ('post_comments', 'user_id'),

            # 4. Delete posts
            ('posts', 'user_id'),

            # 5. Delete messages and conversations
            ('messages', 'sender_id'),
            ('conversation_participants', 'user_id'),

            # 6. Delete connections (both directions)
            ('user_connections', 'follower_id'),
            ('user_connections', 'following_id'),

            # 7. Delete podcast data
            ('user_listening_progress', 'user_id'),
            ('user_podcast_follows', 'user_id'),
            ('podcast_claims', 'user_id'),

            # 8. Delete activity and tracking
            ('user_activity', 'user_id'),
            ('user_signup_tracking', 'user_id'),
            ('user_onboarding', 'id'),

            # 9. Delete settings
            ('user_notification_preferences', 'user_id'),
            ('user_privacy_settings', 'user_id'),

            # 10. Delete profile (last)
            ('user_profiles', 'user_id'),
        ]

        for table_name, column_name in deletion_order:
            try:
                self.supabase.table(table_name).delete().eq(column_name, user_id).execute()
                results[f"{table_name}_{column_name}"] = True
                logger.info(f"Deleted {table_name} records for user {user_id}")
            except Exception as e:
                logger.error(f"Error deleting from {table_name}: {e}")
                results[f"{table_name}_{column_name}"] = False

        return results

    async def _create_deletion_log(
        self,
        user_id: str,
        user_data: Dict[str, Any],
        deletion_counts: Dict[str, int],
        deletion_reason: Optional[str],
        deleted_by: Optional[str],
        ip_address: Optional[str],
        user_agent: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Create deletion log entry"""
        try:
            log_data = {
                'user_id': user_id,
                'email': user_data.get('email'),
                'username': user_data.get('username'),
                'first_name': user_data.get('first_name'),
                'last_name': user_data.get('last_name'),
                'account_created_at': user_data.get('account_created_at'),
                'deleted_at': datetime.now(timezone.utc).isoformat(),
                'deleted_by': deleted_by,
                'deletion_reason': deletion_reason,
                'user_profile_snapshot': user_data.get('profile_data'),
                'deletion_metadata': deletion_counts,
                'ip_address': ip_address,
                'user_agent': user_agent
            }

            result = self.supabase.table('user_deletion_log').insert(log_data).execute()

            if result.data:
                logger.info(f"Created deletion log for user {user_id}: {result.data[0]['id']}")
                return result.data[0]

            return None

        except Exception as e:
            logger.error(f"Error creating deletion log: {e}")
            return None


# Global instance
_account_deletion_service = None


def get_account_deletion_service() -> AccountDeletionService:
    """Get or create global AccountDeletionService instance"""
    global _account_deletion_service
    if _account_deletion_service is None:
        _account_deletion_service = AccountDeletionService()
    return _account_deletion_service
