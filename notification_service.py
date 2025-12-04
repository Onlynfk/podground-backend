"""
Notification Service
Handles creation, retrieval, and management of user notifications for SSE streaming
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

from supabase_client import get_supabase_client
from user_profile_cache_service import get_user_profile_cache_service
from datetime_utils import format_datetime_central

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """Notification types matching database enum"""
    MESSAGE = "message"
    MESSAGE_REACTION = "message_reaction"
    POST_COMMENT = "post_comment"
    POST_LIKE = "post_like"
    COMMENT_LIKE = "comment_like"
    CONNECTION_REQUEST = "connection_request"
    CONNECTION_ACCEPTED = "connection_accepted"
    MENTION = "mention"


class NotificationManager:
    """
    Manages active SSE connections for real-time notification delivery.
    Maintains a registry of connected users and their queues.
    """
    def __init__(self):
        # user_id -> asyncio.Queue mapping
        self.connections: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def add_connection(self, user_id: str) -> asyncio.Queue:
        """Register a new SSE connection for a user"""
        queue = asyncio.Queue()
        async with self._lock:
            if user_id not in self.connections:
                self.connections[user_id] = []
            self.connections[user_id].append(queue)
            logger.info(f"Added SSE connection for user {user_id}. Total connections: {len(self.connections[user_id])}")
        return queue

    async def remove_connection(self, user_id: str, queue: asyncio.Queue):
        """Unregister an SSE connection"""
        async with self._lock:
            if user_id in self.connections:
                try:
                    self.connections[user_id].remove(queue)
                    if not self.connections[user_id]:
                        del self.connections[user_id]
                    logger.info(f"Removed SSE connection for user {user_id}")
                except ValueError:
                    pass

    async def send_to_user(self, user_id: str, notification: Dict[str, Any]):
        """Send notification to all active connections for a user"""
        queues = []
        async with self._lock:
            if user_id in self.connections:
                queues = self.connections[user_id].copy()

        # Send outside the lock to avoid blocking
        for queue in queues:
            try:
                await queue.put(notification)
            except Exception as e:
                logger.error(f"Failed to send notification to queue: {e}")

    def get_active_users(self) -> List[str]:
        """Get list of users with active SSE connections"""
        return list(self.connections.keys())


# Global notification manager instance
notification_manager = NotificationManager()


class NotificationService:
    """Service for creating and managing notifications"""

    def __init__(self):
        self.supabase_client = get_supabase_client()

    async def create_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        related_user_id: Optional[str] = None,
        related_post_id: Optional[str] = None,
        related_message_id: Optional[str] = None,
        related_comment_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new notification and send it to active SSE connections

        Args:
            user_id: Recipient of the notification
            notification_type: Type of notification
            title: Short title
            message: Notification message
            related_user_id: User who triggered this notification
            related_post_id: Related post ID if applicable
            related_message_id: Related message ID if applicable
            related_comment_id: Related comment ID if applicable
            data: Additional flexible data

        Returns:
            Created notification dict or None if failed
        """
        try:
            # Don't create notification if user is notifying themselves
            if related_user_id and user_id == related_user_id:
                logger.debug(f"Skipping self-notification for user {user_id}")
                return None

            notification_data = {
                "user_id": user_id,
                "type": notification_type.value,
                "title": title,
                "message": message,
                "related_user_id": related_user_id,
                "related_post_id": related_post_id,
                "related_message_id": related_message_id,
                "related_comment_id": related_comment_id,
                "data": data or {},
                "is_read": False
            }

            # Insert into database
            result = self.supabase_client.service_client.table("notifications").insert(
                notification_data
            ).execute()

            if result.data:
                notification = result.data[0]
                logger.info(f"Created notification {notification['id']} for user {user_id}")

                # Increment cached unread count
                cache = get_user_profile_cache_service()
                cache.increment_notification_count(user_id)

                # Send to active SSE connections immediately
                await notification_manager.send_to_user(user_id, notification)

                return notification

            return None

        except Exception as e:
            logger.error(f"Failed to create notification: {str(e)}")
            return None

    async def get_notifications(
        self,
        user_id: str,
        limit: int = 50,
        unread_only: bool = False,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get notifications for a user

        Args:
            user_id: User ID
            limit: Maximum number of notifications to return
            unread_only: If True, only return unread notifications
            offset: Pagination offset

        Returns:
            List of notifications
        """
        try:
            query = self.supabase_client.service_client.table("notifications").select(
                "*"
            ).eq("user_id", user_id).order("created_at", desc=True).limit(limit).range(offset, offset + limit - 1)

            if unread_only:
                query = query.eq("is_read", False)

            result = query.execute()

            # Format datetime fields to Central Time
            notifications = result.data or []
            for notification in notifications:
                if 'created_at' in notification:
                    notification['created_at'] = format_datetime_central(notification['created_at'])
                if 'read_at' in notification:
                    notification['read_at'] = format_datetime_central(notification['read_at'])

            return notifications

        except Exception as e:
            logger.error(f"Failed to get notifications for user {user_id}: {str(e)}")
            return []

    async def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """
        Mark a notification as read

        Args:
            notification_id: Notification ID
            user_id: User ID (for verification)

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.supabase_client.service_client.table("notifications").update({
                "is_read": True,
                "read_at": datetime.utcnow().isoformat()
            }).eq("id", notification_id).eq("user_id", user_id).execute()

            if len(result.data) > 0:
                # Decrement cached unread count
                cache = get_user_profile_cache_service()
                cache.decrement_notification_count(user_id)
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to mark notification {notification_id} as read: {str(e)}")
            return False

    async def mark_all_as_read(self, user_id: str) -> bool:
        """
        Mark all notifications as read for a user

        Args:
            user_id: User ID

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.supabase_client.service_client.table("notifications").update({
                "is_read": True,
                "read_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).eq("is_read", False).execute()

            logger.info(f"Marked {len(result.data)} notifications as read for user {user_id}")

            # Set cached unread count to 0
            cache = get_user_profile_cache_service()
            cache.set_notification_count(user_id, 0)

            return True

        except Exception as e:
            logger.error(f"Failed to mark all notifications as read for user {user_id}: {str(e)}")
            return False

    async def get_unread_count(self, user_id: str) -> int:
        """
        Get count of unread notifications (cached)

        Args:
            user_id: User ID

        Returns:
            Count of unread notifications
        """
        try:
            # Check cache first
            cache = get_user_profile_cache_service()
            cached_count = cache.get_notification_count(user_id)

            if cached_count is not None:
                logger.debug(f"Returning cached unread count for user {user_id}: {cached_count}")
                return cached_count

            # Cache miss - fetch from database
            result = self.supabase_client.service_client.table("notifications").select(
                "id", count="exact"
            ).eq("user_id", user_id).eq("is_read", False).execute()

            count = result.count or 0

            # Cache the count (5 minute TTL)
            cache.set_notification_count(user_id, count)
            logger.debug(f"Cached unread count for user {user_id}: {count}")

            return count

        except Exception as e:
            logger.error(f"Failed to get unread count for user {user_id}: {str(e)}")
            return 0

    async def delete_notification(self, notification_id: str, user_id: str) -> bool:
        """
        Delete a notification

        Args:
            notification_id: Notification ID
            user_id: User ID (for verification)

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.supabase_client.service_client.table("notifications").delete().eq(
                "id", notification_id
            ).eq("user_id", user_id).execute()

            if len(result.data) > 0:
                # Invalidate cached count (we don't know if deleted notification was unread)
                cache = get_user_profile_cache_service()
                cache.invalidate_notification_count(user_id)
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to delete notification {notification_id}: {str(e)}")
            return False

    # Helper methods for creating specific notification types

    async def notify_new_message(
        self,
        recipient_id: str,
        sender_id: str,
        sender_name: str,
        message_id: str,
        message_preview: str
    ):
        """Create notification for new message"""
        # Check if user has direct message notifications enabled
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                recipient_id,
                "direct_messages",
                "both"
            )
            if not can_send:
                logger.debug(f"User {recipient_id} has direct message notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=recipient_id,
            notification_type=NotificationType.MESSAGE,
            title="New Message",
            message=f"{sender_name} sent you a message",
            related_user_id=sender_id,
            related_message_id=message_id,
            data={"message_preview": message_preview[:100]}
        )

    async def notify_message_reaction(
        self,
        message_author_id: str,
        reactor_id: str,
        reactor_name: str,
        message_id: str,
        emoji: str
    ):
        """Create notification for message reaction"""
        # Check if user has reaction notifications enabled (using replies_to_comments preference)
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                message_author_id,
                "replies_to_comments",
                "both"
            )
            if not can_send:
                logger.debug(f"User {message_author_id} has reaction notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=message_author_id,
            notification_type=NotificationType.MESSAGE_REACTION,
            title="Message Reaction",
            message=f"{reactor_name} reacted {emoji} to your message",
            related_user_id=reactor_id,
            related_message_id=message_id,
            data={"emoji": emoji}
        )

    async def notify_post_comment(
        self,
        post_author_id: str,
        commenter_id: str,
        commenter_name: str,
        post_id: str,
        comment_preview: str
    ):
        """Create notification for post comment"""
        # Check if user has comment notifications enabled
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                post_author_id,
                "replies_to_comments",
                "both"
            )
            if not can_send:
                logger.debug(f"User {post_author_id} has comment notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=post_author_id,
            notification_type=NotificationType.POST_COMMENT,
            title="New Comment",
            message=f"{commenter_name} commented on your post",
            related_user_id=commenter_id,
            related_post_id=post_id,
            data={"comment_preview": comment_preview[:100]}
        )

    async def notify_post_like(
        self,
        post_author_id: str,
        liker_id: str,
        liker_name: str,
        post_id: str
    ):
        """Create notification for post like"""
        # Check if user has like notifications enabled (using replies_to_comments preference)
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                post_author_id,
                "replies_to_comments",
                "both"
            )
            if not can_send:
                logger.debug(f"User {post_author_id} has like notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=post_author_id,
            notification_type=NotificationType.POST_LIKE,
            title="Post Liked",
            message=f"{liker_name} liked your post",
            related_user_id=liker_id,
            related_post_id=post_id
        )

    async def notify_comment_like(
        self,
        comment_author_id: str,
        liker_id: str,
        liker_name: str,
        comment_id: str,
        post_id: str
    ):
        """Create notification for comment like"""
        # Check if user has like notifications enabled (using replies_to_comments preference)
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                comment_author_id,
                "replies_to_comments",
                "both"
            )
            if not can_send:
                logger.debug(f"User {comment_author_id} has like notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=comment_author_id,
            notification_type=NotificationType.COMMENT_LIKE,
            title="Comment Liked",
            message=f"{liker_name} liked your comment",
            related_user_id=liker_id,
            related_comment_id=comment_id,
            related_post_id=post_id
        )

    async def notify_connection_request(
        self,
        recipient_id: str,
        requester_id: str,
        requester_name: str
    ):
        """Create notification for connection request"""
        # Check if user has follower notifications enabled
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                recipient_id,
                "new_follower",
                "both"
            )
            if not can_send:
                logger.debug(f"User {recipient_id} has follower notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=recipient_id,
            notification_type=NotificationType.CONNECTION_REQUEST,
            title="Connection Request",
            message=f"{requester_name} wants to connect with you",
            related_user_id=requester_id
        )

    async def notify_connection_accepted(
        self,
        requester_id: str,
        accepter_id: str,
        accepter_name: str
    ):
        """Create notification for accepted connection"""
        # Check if user has follower notifications enabled
        try:
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()
            can_send = await settings_service.can_send_notification(
                requester_id,
                "new_follower",
                "both"
            )
            if not can_send:
                logger.debug(f"User {requester_id} has follower notifications disabled")
                return None
        except Exception as e:
            logger.error(f"Error checking notification preferences: {e}")
            # Fail open - send notification if check fails

        return await self.create_notification(
            user_id=requester_id,
            notification_type=NotificationType.CONNECTION_ACCEPTED,
            title="Connection Accepted",
            message=f"{accepter_name} accepted your connection request",
            related_user_id=accepter_id
        )
