"""
Episode Listen Service
Handles tracking when users start listening to podcast episodes.
Used for notifications and analytics.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from supabase import create_client, Client
import os

logger = logging.getLogger(__name__)


class EpisodeListenService:
    """Service for tracking episode listens"""

    def __init__(self):
        """Initialize service with Supabase client"""
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY")

        if not supabase_url or not supabase_service_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment"
            )

        self.supabase_client = create_client(supabase_url, supabase_service_key)

    def record_episode_listen(
        self, user_id: str, episode_id: str, podcast_id: str
    ) -> Dict[str, Any]:
        """
        Record when a user starts listening to an episode.
        Returns info about whether this is the first listen.

        Args:
            user_id: ID of the user listening
            episode_id: ID of the episode being listened to
            podcast_id: ID of the podcast the episode belongs to

        Returns:
            Dict with:
                - success: bool
                - is_first_listen: bool (True if this is the first time user listened)
                - error: Optional error message
        """
        try:
            # Check if this listen already exists
            existing_listen = (
                self.supabase_client.table("episode_listens")
                .select("id, listened_at")
                .eq("user_id", user_id)
                .eq("episode_id", episode_id)
                .execute()
            )

            is_first_listen = len(existing_listen.data) == 0

            if is_first_listen:
                # Insert new listen record
                listen_data = {
                    "user_id": user_id,
                    "episode_id": episode_id,
                    "podcast_id": podcast_id,
                    "listened_at": datetime.utcnow().isoformat(),
                }

                result = (
                    self.supabase_client.table("episode_listens")
                    .insert(listen_data)
                    .execute()
                )

                logger.info(
                    f"Recorded first listen for user {user_id} on episode {episode_id}"
                )
            else:
                # Update listened_at timestamp
                result = (
                    self.supabase_client.table("episode_listens")
                    .update({"listened_at": datetime.utcnow().isoformat()})
                    .eq("user_id", user_id)
                    .eq("episode_id", episode_id)
                    .execute()
                )

                logger.info(
                    f"Updated listen timestamp for user {user_id} on episode {episode_id}"
                )

            return {
                "success": True,
                "is_first_listen": is_first_listen,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error recording episode listen: {str(e)}", exc_info=True)
            return {
                "success": False,
                "is_first_listen": False,
                "error": str(e),
            }

    def get_episode_listen(
        self, user_id: str, episode_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get listen record for a specific user and episode.

        Args:
            user_id: ID of the user
            episode_id: ID of the episode

        Returns:
            Listen record dict if exists, None otherwise
        """
        try:
            result = (
                self.supabase_client.table("episode_listens")
                .select("*")
                .eq("user_id", user_id)
                .eq("episode_id", episode_id)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return result.data[0]

            return None

        except Exception as e:
            logger.error(
                f"Error fetching episode listen: {str(e)}", exc_info=True
            )
            return None

    def get_user_listens(
        self, user_id: str, podcast_id: Optional[str] = None
    ) -> list:
        """
        Get all episode listens for a user, optionally filtered by podcast.

        Args:
            user_id: ID of the user
            podcast_id: Optional podcast ID to filter by

        Returns:
            List of listen records
        """
        try:
            query = (
                self.supabase_client.table("episode_listens")
                .select("*")
                .eq("user_id", user_id)
                .order("listened_at", desc=True)
            )

            if podcast_id:
                query = query.eq("podcast_id", podcast_id)

            result = query.execute()
            return result.data

        except Exception as e:
            logger.error(
                f"Error fetching user listens: {str(e)}", exc_info=True
            )
            return []

    def get_episode_listen_count(self, episode_id: str) -> int:
        """
        Get the total number of unique users who have listened to an episode.

        Args:
            episode_id: ID of the episode

        Returns:
            Count of unique listeners
        """
        try:
            result = (
                self.supabase_client.table("episode_listens")
                .select("id", count="exact")
                .eq("episode_id", episode_id)
                .execute()
            )

            return result.count if result.count else 0

        except Exception as e:
            logger.error(
                f"Error counting episode listens: {str(e)}", exc_info=True
            )
            return 0

    def get_podcast_listen_count(self, podcast_id: str) -> int:
        """
        Get the total number of episode listens for a podcast.

        Args:
            podcast_id: ID of the podcast

        Returns:
            Count of total listens across all episodes
        """
        try:
            result = (
                self.supabase_client.table("episode_listens")
                .select("id", count="exact")
                .eq("podcast_id", podcast_id)
                .execute()
            )

            return result.count if result.count else 0

        except Exception as e:
            logger.error(
                f"Error counting podcast listens: {str(e)}", exc_info=True
            )
            return 0
