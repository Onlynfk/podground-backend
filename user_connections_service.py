"""
User Connections Service
Handles user connection requests and management
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class UserConnectionsService:
    def __init__(self):
        self.supabase_client = SupabaseClient()

    async def get_user_connections(
        self,
        user_id: str,
        status: Optional[str] = "accepted",
        limit: int = 50,
        offset: int = 0,
        viewing_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get user's connections with profile data"""
        try:
            # Build query for connections where user is either requester or requestee
            query = self.supabase_client.service_client.table("user_connections").select(
                "*"
            )

            # Filter by status if provided
            if status:
                query = query.eq("status", status)

            # Filter by user (either follower or following)
            query = query.or_(
                f"follower_id.eq.{user_id},following_id.eq.{user_id}"
            )

            # Apply pagination
            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

            result = query.execute()

            if not result.data:
                return {"connections": [], "total": 0}

            # Get the other user's IDs (the connection partner)
            connection_user_ids = []
            for conn in result.data:
                if conn["follower_id"] == user_id:
                    connection_user_ids.append(conn["following_id"])
                else:
                    connection_user_ids.append(conn["follower_id"])

            # Get user profiles for connections
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(connection_user_ids)
            profiles_map = {u["id"]: u for u in user_profiles}

            # Check for existing conversations if viewing user is authenticated
            conversations_map = {}
            if viewing_user_id:
                # Get viewing user's conversations
                user_conversations_result = self.supabase_client.service_client.table('conversation_participants') \
                    .select('conversation_id') \
                    .eq('user_id', viewing_user_id) \
                    .is_('left_at', 'null') \
                    .execute()

                user_conversation_ids = [c['conversation_id'] for c in (user_conversations_result.data or [])]

                if user_conversation_ids:
                    # Get all participants for these conversations
                    all_participants = self.supabase_client.service_client.table('conversation_participants') \
                        .select('conversation_id, user_id') \
                        .in_('conversation_id', user_conversation_ids) \
                        .is_('left_at', 'null') \
                        .execute()

                    # Group participants by conversation_id
                    conv_participants = {}
                    for participant in (all_participants.data or []):
                        conv_id = participant['conversation_id']
                        if conv_id not in conv_participants:
                            conv_participants[conv_id] = []
                        conv_participants[conv_id].append(participant['user_id'])

                    # Build map of other_user_id -> conversation_id (only for direct conversations)
                    for conv_id, participant_ids in conv_participants.items():
                        if len(participant_ids) == 2 and viewing_user_id in participant_ids:
                            other_user_id = [uid for uid in participant_ids if uid != viewing_user_id][0]
                            conversations_map[other_user_id] = conv_id

            # Combine connection data with user profiles
            connections = []
            for conn in result.data:
                other_user_id = conn["following_id"] if conn["follower_id"] == user_id else conn["follower_id"]
                is_requester = conn["follower_id"] == user_id

                # Get profile and add conversation info
                user_profile = profiles_map.get(other_user_id, {"id": other_user_id})
                conversation_id = conversations_map.get(other_user_id)

                connection_data = {
                    "connection_id": conn["id"],
                    "user": user_profile,
                    "status": conn["status"],
                    "is_requester": is_requester,
                    "created_at": conn["created_at"],
                    "accepted_at": conn.get("accepted_at"),
                    "has_conversation": conversation_id is not None,
                    "conversation_id": conversation_id
                }
                connections.append(connection_data)

            return {
                "connections": connections,
                "total": len(connections)
            }

        except Exception as e:
            logger.error(f"Failed to get user connections for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get connections: {str(e)}")

    async def get_pending_requests(self, user_id: str) -> Dict[str, Any]:
        """Get pending connection requests - both incoming (sent to user) and outgoing (sent by user)"""
        try:
            # Get incoming requests (where user is being followed)
            incoming_result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).eq("following_id", user_id).eq("status", "pending").order(
                "created_at", desc=True
            ).execute()

            # Get outgoing requests (where user is the follower)
            outgoing_result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).eq("follower_id", user_id).eq("status", "pending").order(
                "created_at", desc=True
            ).execute()

            incoming_requests = []
            outgoing_requests = []

            # Process incoming requests
            if incoming_result.data:
                requester_ids = [conn["follower_id"] for conn in incoming_result.data]
                from user_profile_service import UserProfileService
                profile_service = UserProfileService()
                user_profiles = await profile_service.get_users_by_ids(requester_ids)
                profiles_map = {u["id"]: u for u in user_profiles}

                for conn in incoming_result.data:
                    request_data = {
                        "request_id": conn["id"],
                        "user": profiles_map.get(conn["follower_id"], {"id": conn["follower_id"]}),
                        "created_at": conn["created_at"],
                        "direction": "incoming"
                    }
                    incoming_requests.append(request_data)

            # Process outgoing requests
            if outgoing_result.data:
                requestee_ids = [conn["following_id"] for conn in outgoing_result.data]
                from user_profile_service import UserProfileService
                profile_service = UserProfileService()
                user_profiles = await profile_service.get_users_by_ids(requestee_ids)
                profiles_map = {u["id"]: u for u in user_profiles}

                for conn in outgoing_result.data:
                    request_data = {
                        "request_id": conn["id"],
                        "user": profiles_map.get(conn["following_id"], {"id": conn["following_id"]}),
                        "created_at": conn["created_at"],
                        "direction": "outgoing"
                    }
                    outgoing_requests.append(request_data)

            return {
                "incoming": incoming_requests,
                "outgoing": outgoing_requests,
                "total_incoming": len(incoming_requests),
                "total_outgoing": len(outgoing_requests)
            }

        except Exception as e:
            logger.error(f"Failed to get pending requests for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get pending requests: {str(e)}")

    async def send_connection_request(self, requester_id: str, requestee_id: str) -> Dict[str, Any]:
        """Send connection request to another user"""
        try:
            # Validate users are different
            if requester_id == requestee_id:
                raise HTTPException(400, "Cannot connect with yourself")

            # Check if requestee exists
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()

            try:
                await profile_service.get_user_profile(requestee_id)
            except:
                raise HTTPException(404, "User not found")

            # Check if connection already exists (in either direction)
            existing = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).or_(
                f"and(follower_id.eq.{requester_id},following_id.eq.{requestee_id}),and(follower_id.eq.{requestee_id},following_id.eq.{requester_id})"
            ).execute()

            if existing.data:
                existing_conn = existing.data[0]
                if existing_conn["status"] == "accepted":
                    raise HTTPException(400, "Already connected")
                elif existing_conn["status"] == "pending":
                    raise HTTPException(400, "Connection request already pending")
                elif existing_conn["status"] == "rejected":
                    # Allow re-requesting after rejection
                    pass

            # Delete any old rejected connections
            self.supabase_client.service_client.table("user_connections").delete().or_(
                f"and(follower_id.eq.{requester_id},following_id.eq.{requestee_id}),and(follower_id.eq.{requestee_id},following_id.eq.{requester_id})"
            ).execute()

            # Create new connection request
            result = self.supabase_client.service_client.table("user_connections").insert({
                "follower_id": requester_id,
                "following_id": requestee_id,
                "status": "pending"
            }).execute()

            if not result.data:
                raise Exception("Failed to create connection request")

            # Log activity
            await self._log_activity(requester_id, "connection_request_sent", {
                "requestee_id": requestee_id,
                "connection_id": result.data[0]["id"]
            })

            await self._log_activity(requestee_id, "connection_request_received", {
                "requester_id": requester_id,
                "connection_id": result.data[0]["id"]
            })

            return {
                "success": True,
                "connection_id": result.data[0]["id"],
                "status": "pending"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to send connection request: {str(e)}")
            raise HTTPException(500, f"Failed to send connection request: {str(e)}")

    async def accept_connection_request(self, user_id: str, request_id: str) -> Dict[str, Any]:
        """Accept a connection request"""
        try:
            # Get the connection request
            result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).eq("id", request_id).execute()

            if not result.data:
                raise HTTPException(404, "Connection request not found")

            connection = result.data[0]

            # Verify user is the one being followed
            if connection["following_id"] != user_id:
                raise HTTPException(403, "Not authorized to accept this request")

            # Verify status is pending
            if connection["status"] != "pending":
                raise HTTPException(400, f"Request is already {connection['status']}")

            # Update status to accepted
            update_result = self.supabase_client.service_client.table("user_connections").update({
                "status": "accepted",
                "accepted_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", request_id).execute()

            if not update_result.data:
                raise Exception("Failed to accept connection request")

            # Log activity for both users
            await self._log_activity(user_id, "connection_accepted", {
                "connection_id": request_id,
                "connected_user_id": connection["follower_id"]
            })

            await self._log_activity(connection["follower_id"], "connection_accepted", {
                "connection_id": request_id,
                "connected_user_id": user_id
            })

            return {
                "success": True,
                "connection_id": request_id,
                "status": "accepted"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to accept connection request: {str(e)}")
            raise HTTPException(500, f"Failed to accept connection: {str(e)}")

    async def decline_connection_request(self, user_id: str, request_id: str) -> Dict[str, Any]:
        """Decline a connection request"""
        try:
            # Get the connection request
            result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).eq("id", request_id).execute()

            if not result.data:
                raise HTTPException(404, "Connection request not found")

            connection = result.data[0]

            # Verify user is the one being followed
            if connection["following_id"] != user_id:
                raise HTTPException(403, "Not authorized to decline this request")

            # Verify status is pending
            if connection["status"] != "pending":
                raise HTTPException(400, f"Request is already {connection['status']}")

            # Update status to rejected
            update_result = self.supabase_client.service_client.table("user_connections").update({
                "status": "rejected"
            }).eq("id", request_id).execute()

            if not update_result.data:
                raise Exception("Failed to decline connection request")

            return {
                "success": True,
                "connection_id": request_id,
                "status": "rejected"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to decline connection request: {str(e)}")
            raise HTTPException(500, f"Failed to decline connection: {str(e)}")

    async def remove_connection(self, user_id: str, connection_id: str) -> Dict[str, Any]:
        """Remove/cancel a connection"""
        try:
            # Get the connection
            result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).eq("id", connection_id).execute()

            if not result.data:
                raise HTTPException(404, "Connection not found")

            connection = result.data[0]

            # Verify user is part of this connection
            if connection["follower_id"] != user_id and connection["following_id"] != user_id:
                raise HTTPException(403, "Not authorized to remove this connection")

            # Delete the connection
            delete_result = self.supabase_client.service_client.table("user_connections").delete().eq(
                "id", connection_id
            ).execute()

            if not delete_result.data:
                raise Exception("Failed to remove connection")

            # Log activity
            other_user_id = connection["following_id"] if connection["follower_id"] == user_id else connection["follower_id"]

            await self._log_activity(user_id, "connection_removed", {
                "connection_id": connection_id,
                "removed_user_id": other_user_id
            })

            return {"success": True}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to remove connection: {str(e)}")
            raise HTTPException(500, f"Failed to remove connection: {str(e)}")

    async def check_connection_status(self, user_id: str, other_user_id: str) -> Dict[str, Any]:
        """Check connection status between two users"""
        try:
            # Check if connection exists in either direction
            result = self.supabase_client.service_client.table("user_connections").select(
                "*"
            ).or_(
                f"and(follower_id.eq.{user_id},following_id.eq.{other_user_id}),and(follower_id.eq.{other_user_id},following_id.eq.{user_id})"
            ).execute()

            if not result.data:
                return {
                    "connected": False,
                    "status": None,
                    "connection_id": None
                }

            connection = result.data[0]

            return {
                "connected": connection["status"] == "accepted",
                "status": connection["status"],
                "connection_id": connection["id"],
                "is_requester": connection["follower_id"] == user_id
            }

        except Exception as e:
            logger.error(f"Failed to check connection status: {str(e)}")
            raise HTTPException(500, f"Failed to check connection status: {str(e)}")

    async def get_mutual_connections(self, user_id: str, other_user_id: str) -> List[Dict[str, Any]]:
        """Get mutual connections between two users"""
        try:
            # Get user's connections
            user_connections_result = self.supabase_client.service_client.table("user_connections").select(
                "follower_id, following_id"
            ).eq("status", "accepted").or_(
                f"follower_id.eq.{user_id},following_id.eq.{user_id}"
            ).execute()

            # Get other user's connections
            other_connections_result = self.supabase_client.service_client.table("user_connections").select(
                "follower_id, following_id"
            ).eq("status", "accepted").or_(
                f"follower_id.eq.{other_user_id},following_id.eq.{other_user_id}"
            ).execute()

            # Extract connection user IDs
            user_conn_ids = set()
            for conn in user_connections_result.data or []:
                user_conn_ids.add(conn["follower_id"] if conn["following_id"] == user_id else conn["following_id"])

            other_conn_ids = set()
            for conn in other_connections_result.data or []:
                other_conn_ids.add(conn["follower_id"] if conn["following_id"] == other_user_id else conn["following_id"])

            # Find mutual connections
            mutual_ids = list(user_conn_ids & other_conn_ids)

            if not mutual_ids:
                return []

            # Get profiles of mutual connections
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            mutual_users = await profile_service.get_users_by_ids(mutual_ids)

            return mutual_users

        except Exception as e:
            logger.error(f"Failed to get mutual connections: {str(e)}")
            raise HTTPException(500, f"Failed to get mutual connections: {str(e)}")

    async def get_suggested_connections(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get suggested users to connect with (excludes existing connections and respects privacy)"""
        try:
            # Get all user IDs that the user is already connected to or has pending requests with
            existing_connections = self.supabase_client.service_client.table("user_connections").select(
                "follower_id, following_id"
            ).or_(
                f"follower_id.eq.{user_id},following_id.eq.{user_id}"
            ).execute()

            # Build set of user IDs to exclude
            excluded_user_ids = {user_id}  # Exclude self
            for conn in existing_connections.data or []:
                if conn["follower_id"] == user_id:
                    excluded_user_ids.add(conn["following_id"])
                else:
                    excluded_user_ids.add(conn["follower_id"])

            # Get ALL user profiles (not just a limited set) to properly filter
            # We'll apply the limit after filtering by exclusions and privacy
            profiles_result = self.supabase_client.service_client.table("user_profiles").select(
                "user_id"
            ).order("created_at", desc=True).execute()

            if not profiles_result.data:
                return {"suggested_connections": [], "total": 0}

            # Filter out excluded user IDs and collect ALL candidates
            candidate_user_ids = []
            for profile in profiles_result.data:
                if profile["user_id"] not in excluded_user_ids:
                    candidate_user_ids.append(profile["user_id"])

            if not candidate_user_ids:
                return {"suggested_connections": [], "total": 0}

            # Filter by privacy settings - check all candidates first
            from user_settings_service import get_user_settings_service
            settings_service = get_user_settings_service()

            searchable_user_ids = []
            for candidate_id in candidate_user_ids:
                try:
                    is_searchable = await settings_service.is_user_searchable(candidate_id)
                    if is_searchable:
                        searchable_user_ids.append(candidate_id)
                except Exception as e:
                    logger.warning(f"Error checking searchability for user {candidate_id}: {e}")
                    # Fail open - include user if we can't check
                    searchable_user_ids.append(candidate_id)

            if not searchable_user_ids:
                return {"suggested_connections": [], "total": 0}

            # Now apply pagination AFTER filtering
            paginated_user_ids = searchable_user_ids[offset:offset + limit]

            if not paginated_user_ids:
                return {"suggested_connections": [], "total": len(searchable_user_ids)}

            # Get full user profiles using the existing method
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            suggested_users = await profile_service.get_users_by_ids(paginated_user_ids)

            # Check for existing conversations with suggested users
            conversations_map = {}
            if paginated_user_ids:
                # Get user's conversations
                user_conversations_result = self.supabase_client.service_client.table('conversation_participants') \
                    .select('conversation_id') \
                    .eq('user_id', user_id) \
                    .is_('left_at', 'null') \
                    .execute()

                user_conversation_ids = [c['conversation_id'] for c in (user_conversations_result.data or [])]

                if user_conversation_ids:
                    # Get all participants for these conversations
                    all_participants = self.supabase_client.service_client.table('conversation_participants') \
                        .select('conversation_id, user_id') \
                        .in_('conversation_id', user_conversation_ids) \
                        .is_('left_at', 'null') \
                        .execute()

                    # Group participants by conversation_id
                    conv_participants = {}
                    for participant in (all_participants.data or []):
                        conv_id = participant['conversation_id']
                        if conv_id not in conv_participants:
                            conv_participants[conv_id] = []
                        conv_participants[conv_id].append(participant['user_id'])

                    # Build map of other_user_id -> conversation_id (only for direct conversations)
                    for conv_id, participant_ids in conv_participants.items():
                        if len(participant_ids) == 2 and user_id in participant_ids:
                            other_user_id = [uid for uid in participant_ids if uid != user_id][0]
                            conversations_map[other_user_id] = conv_id

            # Add has_conversation field to each suggested user
            for user in suggested_users:
                conversation_id = conversations_map.get(user['id'])
                user['has_conversation'] = conversation_id is not None
                user['conversation_id'] = conversation_id

            return {
                "suggested_connections": suggested_users,
                "total": len(searchable_user_ids)  # Total available, not just this page
            }

        except Exception as e:
            logger.error(f"Failed to get suggested connections for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get suggested connections: {str(e)}")

    async def _log_activity(self, user_id: str, activity_type: str, activity_data: Dict[str, Any]):
        """Log user activity"""
        try:
            from user_activity_service import get_user_activity_service
            activity_service = get_user_activity_service()
            await activity_service.log_activity(user_id, activity_type, activity_data)
        except Exception as e:
            logger.warning(f"Failed to log activity: {str(e)}")


# Global instance
_user_connections_service = None

def get_user_connections_service() -> UserConnectionsService:
    """Get or create global UserConnectionsService instance"""
    global _user_connections_service
    if _user_connections_service is None:
        _user_connections_service = UserConnectionsService()
    return _user_connections_service
