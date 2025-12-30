import os
import requests
import json
from typing import Dict, List, Optional, Any
import logging
from supabase import create_client, Client
from supabase_posts_client import SupabasePostsClient

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY")
        self.service_key = os.getenv(
            "SUPABASE_SERVICE_KEY"
        )  # Keep for admin operations only

        if not self.url or not self.anon_key:
            logger.warning(
                "Supabase URL or anon key not found in environment variables"
            )
            self.client = None
            self.service_client = None
        else:
            # Create official Supabase clients (PKCE is default in newer versions)
            self.client: Client = create_client(self.url, self.anon_key)
            # Service client for admin operations (bypasses RLS)
            self.service_client: Client = (
                create_client(self.url, self.service_key)
                if self.service_key
                else None
            )

            # Keep headers for backward compatibility with REST methods
            self.base_headers = {
                "apikey": self.anon_key,
                "Content-Type": "application/json",
            }

            # Initialize posts client extension
            self.posts = SupabasePostsClient(self)

    def _get_headers(
        self, user_token: str = None, use_service_key: bool = False
    ):
        """Get headers with appropriate authorization"""
        headers = self.base_headers.copy()

        if use_service_key and self.service_key:
            # Use service key for admin operations (bypasses RLS)
            headers["Authorization"] = f"Bearer {self.service_key}"
        elif user_token:
            # Use user's JWT token (respects RLS)
            headers["Authorization"] = f"Bearer {user_token}"
        else:
            # Use anon key only (public access)
            headers["Authorization"] = f"Bearer {self.anon_key}"

        return headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Dict = None,
        user_token: str = None,
        use_service_key: bool = False,
    ) -> Dict:
        """Make HTTP request to Supabase API"""
        if not self.client:
            return {
                "success": False,
                "error": "Supabase client not initialized",
            }

        url = f"{self.url}/rest/v1/{endpoint}"
        headers = self._get_headers(user_token, use_service_key)

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=data, timeout=10
                )
            elif method == "PATCH":
                response = requests.patch(
                    url, headers=headers, json=data, timeout=10
                )
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=10)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported HTTP method: {method}",
                }

            if response.status_code in [200, 201, 204]:
                return {
                    "success": True,
                    "data": response.json() if response.content else None,
                }
            else:
                return {
                    "success": False,
                    "error": response.text,
                    "status_code": response.status_code,
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Supabase request failed: {str(e)}")
            return {"success": False, "error": f"Request failed: {str(e)}"}

    # Authentication methods using official Supabase client
    def sign_up_user_with_magic_link(
        self, email: str, name: str, redirect_url: str
    ) -> Dict:
        """Sign up user with magic link using official Supabase client"""
        if not self.client:
            return {
                "success": False,
                "error": "Supabase client not initialized",
            }

        try:
            # Split name into first and last
            name_parts = name.strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Use signInWithOtp for both signup and signin as per Supabase guidance
            response = self.client.auth.sign_in_with_otp(
                {
                    "email": email,
                    "options": {
                        "should_create_user": True,  # Allow automatic user creation
                        "data": {
                            "first_name": first_name,
                            "last_name": last_name,
                            "role": "podcaster",  # Default role for new users
                        },
                        "email_redirect_to": redirect_url,
                    },
                }
            )

            return {"success": True, "data": response}

        except Exception as e:
            logger.error(f"Magic link sign up failed: {str(e)}")
            return {
                "success": False,
                "error": f"Magic link sign up failed: {str(e)}",
            }

    def create_user_without_email(self, email: str, name: str) -> Dict:
        """Create user without sending automatic email - for custom email flow"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Split name into first and last
            name_parts = name.strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Create user using admin client to bypass email sending
            response = self.service_client.auth.admin.create_user(
                {
                    "email": email,
                    "user_metadata": {
                        "first_name": first_name,
                        "last_name": last_name,
                        "role": "podcaster",
                    },
                    "email_confirm": False,  # Don't require email confirmation
                }
            )

            # Verify user was created and defaults were assigned by trigger
            if response.user and response.user.id:
                user_id = response.user.id
                logger.info(f"Created user {user_id} with email {email}")

                # Small delay to ensure trigger has executed
                import time

                time.sleep(0.1)

                # Ensure user has proper defaults (fallback if trigger didn't work)
                self.ensure_user_defaults(user_id)
                logger.info(f"User {user_id} defaults verified successfully")

            return {"success": True, "data": response}

        except Exception as e:
            logger.error(f"User creation without email failed: {str(e)}")
            # Check if user already exists
            if (
                "already been registered" in str(e).lower()
                or "already registered" in str(e).lower()
            ):
                return {"success": False, "error": "Email already registered"}
            return {
                "success": False,
                "error": f"User creation failed: {str(e)}",
            }

    def generate_magic_link(
        self,
        email: str,
        frontend_callback_url: str,
        expiry_seconds: int = None,
    ) -> Dict:
        """Generate magic link that will redirect with PKCE authorization code"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Generate magic link using admin client
            # Since we configured the main client with PKCE flow, this should generate
            # a link that redirects with ?code=xxx format instead of ?token=xxx
            response = self.service_client.auth.admin.generate_link(
                {
                    "type": "magiclink",
                    "email": email,
                    "options": {"redirect_to": frontend_callback_url},
                }
            )

            return {"success": True, "data": response}

        except Exception as e:
            logger.error(f"Magic link generation failed: {str(e)}")
            return {
                "success": False,
                "error": f"Magic link generation failed: {str(e)}",
            }

    def generate_short_verification_code(
        self, user_id: str, length: int = 6
    ) -> str:
        """Generate a short numeric verification code for the user"""
        import random

        # Generate a random numeric code
        code = "".join([str(random.randint(0, 9)) for _ in range(length)])

        # Store the code in user metadata for later verification
        try:
            self.service_client.auth.admin.update_user_by_id(
                user_id,
                {
                    "user_metadata": {
                        "verification_code": code,
                        "code_expires_at": "now() + interval '24 hours'",
                    }
                },
            )
            logger.info(f"Generated verification code for user {user_id}")
            return code
        except Exception as e:
            logger.error(f"Failed to store verification code: {str(e)}")
            return code  # Return code even if storage fails

    def get_user_id_by_email(self, email: str) -> Dict:
        """Get user_id from email address"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            user_list = self.service_client.auth.admin.list_users()
            for user in user_list:
                if user.email == email:
                    return {"success": True, "user_id": user.id, "user": user}
            return {"success": False, "error": "User not found"}
        except Exception as e:
            logger.error(f"Failed to get user_id by email: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to get user_id by email: {str(e)}",
            }

    def verify_short_code(self, email: str, code: str) -> Dict:
        """Verify a short numeric verification code and return access token"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Get user by email using the new helper method
            user_result = self.get_user_id_by_email(email)

            if not user_result["success"]:
                return user_result

            user = user_result["user"]

            # Check verification code
            user_metadata = user.user_metadata or {}
            stored_code = user_metadata.get("verification_code")

            if not stored_code:
                return {
                    "success": False,
                    "error": "No verification code found",
                }

            if stored_code != code:
                return {"success": False, "error": "Invalid verification code"}

            # Clear the verification code after successful verification
            from datetime import datetime, timezone

            self.service_client.auth.admin.update_user_by_id(
                user.id,
                {
                    "user_metadata": {
                        **user_metadata,
                        "verification_code": None,
                    }
                },
            )

            # Update last_sign_in_at timestamp
            self.update_last_sign_in_at(user.id)

            return {"success": True, "user_id": user.id}

        except Exception as e:
            logger.error(f"Code verification failed: {str(e)}")
            return {
                "success": False,
                "error": f"Code verification failed: {str(e)}",
            }

    def sign_in_user_with_magic_link(
        self, email: str, redirect_url: str, expiry_seconds: int = None
    ) -> Dict:
        """Sign in user with magic link using official Supabase client"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Use admin generate_link for consistent expiry handling
            options = {"redirect_to": redirect_url}

            # Add custom expiry if specified (24 hours = 86400 seconds)
            if expiry_seconds:
                from datetime import datetime, timedelta, timezone

                expiry_time = datetime.now(timezone.utc) + timedelta(
                    seconds=expiry_seconds
                )
                options["expires_at"] = expiry_time.isoformat()

            response = self.service_client.auth.admin.generate_link(
                {"type": "magiclink", "email": email, "options": options}
            )

            return {"success": True, "data": response}

        except Exception as e:
            logger.error(f"Magic link sign in failed: {str(e)}")
            return {
                "success": False,
                "error": f"Magic link sign in failed: {str(e)}",
            }

    def verify_magic_link_token(
        self, token: str, type: str = "magiclink"
    ) -> Dict:
        """Verify magic link token using official Supabase client"""
        if not self.client:
            return {
                "success": False,
                "error": "Supabase client not initialized",
            }

        try:
            # Use verifyOtp for token verification
            response = self.client.auth.verify_otp(
                {"token": token, "type": type}
            )

            return {"success": True, "data": response}

        except Exception as e:
            logger.error(f"Magic link verification failed: {str(e)}")
            return {
                "success": False,
                "error": f"Magic link verification failed: {str(e)}",
            }

    def exchange_code_for_session(self, code: str) -> Dict:
        """Exchange PKCE authorization code or validate magic link access token for user session"""
        if not self.client:
            return {
                "success": False,
                "error": "Supabase client not initialized",
            }

        # Clean the code and check if this looks like a JWT access token (magic link)
        clean_code = code.strip()

        # Remove any URL parameters that might have gotten attached
        if "&" in clean_code:
            clean_code = clean_code.split("&")[0]
        if "?" in clean_code:
            clean_code = clean_code.split("?")[0]

        if clean_code.startswith("eyJ") and len(clean_code) > 100:
            # This is likely a JWT access token from a magic link
            try:
                logger.info(
                    f"Attempting to validate JWT access token (length: {len(clean_code)})"
                )

                # For JWT tokens, decode and validate them directly using JWT library
                import jwt
                from datetime import datetime, timezone

                try:
                    # Decode the JWT token without verification to get user info
                    # Note: In production, you'd want to verify the signature
                    decoded_token = jwt.decode(
                        clean_code, options={"verify_signature": False}
                    )

                    # Check if token is expired
                    exp = decoded_token.get("exp")
                    if exp and datetime.fromtimestamp(
                        exp, tz=timezone.utc
                    ) < datetime.now(timezone.utc):
                        logger.warning("JWT token is expired")
                        return {"success": False, "error": "Token expired"}

                    # Extract user information
                    user_id = decoded_token.get("sub")
                    email = decoded_token.get("email")

                    if user_id and email:
                        logger.info(
                            f"Successfully decoded JWT token for user {user_id}"
                        )

                        # Update last_sign_in_at for this user
                        self.update_last_sign_in_at(user_id)

                        # Create user object
                        user_obj = type(
                            "User",
                            (),
                            {
                                "id": user_id,
                                "email": email,
                                "user_metadata": decoded_token.get(
                                    "user_metadata", {}
                                ),
                                "app_metadata": decoded_token.get(
                                    "app_metadata", {}
                                ),
                            },
                        )()

                        # Create session object
                        session_obj = type(
                            "Session",
                            (),
                            {
                                "access_token": clean_code,
                                "refresh_token": "",
                                "user": user_obj,
                            },
                        )()

                        return {
                            "success": True,
                            "user": user_obj,
                            "session": session_obj,
                        }
                    else:
                        logger.warning(
                            "JWT token missing required user information"
                        )
                        return {
                            "success": False,
                            "error": "Invalid token format",
                        }

                except jwt.InvalidTokenError as jwt_error:
                    logger.error(f"JWT decoding failed: {jwt_error}")
                except Exception as decode_error:
                    logger.error(f"Token decoding error: {decode_error}")

            except Exception as e:
                logger.error(f"Access token validation failed: {str(e)}")
                # Try to continue with other methods instead of failing immediately
                logger.info("Attempting fallback authentication methods...")

        # Use the cleaned code for all subsequent attempts
        code = clean_code
        # Otherwise, try PKCE code exchange
        try:
            response = self.client.auth.exchange_code_for_session(
                {"auth_code": code}
            )

            if response.session and response.user:
                logger.info("PKCE code exchange successful")
                return {
                    "success": True,
                    "user": response.user,
                    "session": response.session,
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to exchange authorization code",
                }

        except Exception as e:
            logger.error(f"PKCE code exchange failed: {str(e)}")

            # Final fallback: try as OTP verification
            try:
                response = self.client.auth.verify_otp(
                    {"token": code, "type": "magiclink"}
                )

                if response.session and response.user:
                    logger.info("OTP verification fallback successful")
                    return {
                        "success": True,
                        "user": response.user,
                        "session": response.session,
                    }
                else:
                    return {"success": False, "error": "Failed to verify OTP"}

            except Exception as e2:
                logger.error(
                    f"OTP verification fallback also failed: {str(e2)}"
                )
                return {
                    "success": False,
                    "error": f"All authentication methods failed. PKCE: {str(e)}, OTP: {str(e2)}",
                }

    # Profile methods
    def create_user_profile(
        self, user_id: str, first_name: str, last_name: str, user_token: str
    ) -> Dict:
        """Create user profile"""
        data = {
            "id": user_id,
            "first_name": first_name,
            "last_name": last_name,
        }
        return self._make_request(
            "POST", "user_profiles", data, user_token=user_token
        )

    def get_user_profile(self, user_id: str, user_token: str) -> Dict:
        """Get user profile"""
        return self._make_request(
            "GET", f"user_profiles?id=eq.{user_id}", user_token=user_token
        )

    # Onboarding methods
    def save_onboarding_data(
        self, user_id: str, onboarding_data: Dict, user_token: str = None
    ) -> Dict:
        """Save user onboarding data with category junction table"""
        # Extract category_ids before preparing main data
        category_ids = onboarding_data.pop("category_ids", [])

        data = {"id": user_id, **onboarding_data, "completed_at": "now()"}

        # Validate that location_id is provided
        location_id = data.get("location_id")
        if not location_id:
            return {"success": False, "error": "location_id is required"}

        # Validate that category_ids are provided
        if not category_ids or len(category_ids) == 0:
            return {"success": False, "error": "category_ids are required"}

        # Use service client if no user token provided (session-based auth)
        if user_token is None:
            try:
                if not self.service_client:
                    return {
                        "success": False,
                        "error": "Service client not initialized",
                    }

                # Insert main onboarding data
                result = (
                    self.service_client.table("user_onboarding")
                    .insert(data)
                    .execute()
                )

                if result.data:
                    # Insert categories into junction table
                    categories_result = self._save_user_categories(
                        user_id, category_ids
                    )

                    if not categories_result["success"]:
                        # Rollback main insert if categories failed
                        self.service_client.table(
                            "user_onboarding"
                        ).delete().eq("id", user_id).execute()
                        return {
                            "success": False,
                            "error": f"Failed to save categories: {categories_result.get('error')}",
                        }

                    return {"success": True, "data": result.data}
                else:
                    return {
                        "success": False,
                        "error": "Failed to save onboarding data",
                    }
            except Exception as e:
                logger.error(
                    f"Failed to save onboarding data via service client: {str(e)}"
                )
                return {"success": False, "error": str(e)}
        else:
            # Use user token for JWT-based auth (legacy)
            return self._make_request(
                "POST", "user_onboarding", data, user_token=user_token
            )

    def get_onboarding_data(
        self, user_id: str, user_token: str = None
    ) -> Dict:
        """Get user onboarding data"""
        # Use service client if no user token provided (session-based auth)
        if user_token is None:
            try:
                if not self.service_client:
                    return {
                        "success": False,
                        "error": "Service client not initialized",
                    }

                result = (
                    self.service_client.table("user_onboarding")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )

                if result.data is not None:
                    return {"success": True, "data": result.data}
                else:
                    return {
                        "success": False,
                        "error": "Failed to get onboarding data",
                    }
            except Exception as e:
                logger.error(
                    f"Failed to get onboarding data via service client: {str(e)}"
                )
                return {"success": False, "error": str(e)}
        else:
            # Use user token for JWT-based auth (legacy)
            return self._make_request(
                "GET",
                f"user_onboarding?id=eq.{user_id}",
                user_token=user_token,
            )

    def _save_user_categories(
        self, user_id: str, category_ids: List[str]
    ) -> Dict:
        """Save user categories to junction table"""
        try:
            if not self.service_client:
                return {
                    "success": False,
                    "error": "Service client not initialized",
                }

            # Delete existing categories for this user
            self.service_client.table(
                "user_onboarding_categories"
            ).delete().eq("user_id", user_id).execute()

            # Insert new categories
            category_records = [
                {"user_id": user_id, "category_id": category_id}
                for category_id in category_ids
            ]

            # Debug logging
            logger.info(
                f"DEBUG: Inserting category records: {category_records}"
            )
            logger.info(
                f"DEBUG: user_id type: {type(user_id)}, category_ids types: {[type(cid) for cid in category_ids]}"
            )

            result = (
                self.service_client.table("user_onboarding_categories")
                .insert(category_records)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data}
            else:
                return {"success": False, "error": "Failed to save categories"}

        except Exception as e:
            logger.error(f"Failed to save user categories: {str(e)}")
            return {"success": False, "error": str(e)}

    def save_onboarding_step(
        self,
        user_id: str,
        step: int,
        step_data: Dict,
        user_token: str = None,
        automatic_favorites: List[Dict] = None,
    ) -> Dict:
        """Save individual onboarding step data"""
        # First check if user has existing onboarding record
        existing = self.get_onboarding_data(user_id, user_token)

        # Prepare update data based on step
        # Update current_step to next step, or keep at current if this is the last step
        next_step = step + 1 if step < 5 else 5
        update_data = {"current_step": next_step}

        if step == 1:
            # Experience level - Years of podcasting experience
            update_data.update(
                {
                    "podcasting_experience": step_data.get(
                        "podcasting_experience"
                    ),
                    "step_1_completed": True,
                }
            )
        elif step == 2:
            # Podcast categories - Select categories of interest and Part of a network or not
            category_ids = step_data.get("category_ids", [])
            update_data.update(
                {
                    "is_part_of_network": step_data.get(
                        "is_part_of_network", False
                    ),
                    "network_name": step_data.get("network_name"),
                    "step_2_completed": True,
                }
            )

            # Handle categories separately in junction table
            if category_ids:
                categories_result = self._save_user_categories(
                    user_id, category_ids
                )
                if not categories_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to save categories: {categories_result.get('error')}",
                    }
        elif step == 3:
            # Location - Where are you located (State, Country)
            location_id = step_data.get("location_id")

            if not location_id:
                return {
                    "success": False,
                    "error": "location_id is required for step 3",
                }

            update_data.update(
                {"location_id": location_id, "step_3_completed": True}
            )
        elif step == 4:
            # Networking preferences - Looking for guests, wants to be a guest
            update_data.update(
                {
                    "looking_for_guests": step_data.get(
                        "looking_for_guests", False
                    ),
                    "wants_to_be_guest": step_data.get(
                        "wants_to_be_guest", False
                    ),
                    "step_4_completed": True,
                }
            )
        elif step == 5:
            # Favorite podcasts - Select top 5 favorite podcasts
            favorite_podcasts = step_data.get("favorite_podcast_ids", [])

            # Create follows for the listening system (single source of truth)
            if automatic_favorites or favorite_podcasts:
                follows_result = self._create_follows_from_onboarding(
                    user_id, favorite_podcasts, automatic_favorites
                )
                if not follows_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to create follows: {follows_result.get('error')}",
                    }

            # Sync onboarding data to user_profiles when completing final step
            sync_result = self._sync_onboarding_to_profile(user_id)
            if not sync_result["success"]:
                logger.warning(
                    f"Failed to sync onboarding data to profile for user {user_id}: {sync_result.get('error')}"
                )
                # Don't fail the entire onboarding, just log the warning

            update_data.update(
                {
                    # favorite podcasts now stored directly in user_podcast_follows table
                    "step_5_completed": True,
                    "is_completed": True,  # Mark as completed after step 5 (final step)
                    "completed_at": "now()",
                }
            )

        # If no existing record, create new one
        if not existing["success"] or not existing["data"]:
            create_data = {"id": user_id, **update_data}

            if user_token is None:
                # Use service client for session-based auth
                try:
                    result = (
                        self.service_client.table("user_onboarding")
                        .insert(create_data)
                        .execute()
                    )
                    if result.data:
                        return {"success": True, "data": result.data}
                    else:
                        return {
                            "success": False,
                            "error": "Failed to create onboarding record",
                        }
                except Exception as e:
                    logger.error(
                        f"Failed to create onboarding step via service client: {str(e)}"
                    )
                    return {"success": False, "error": str(e)}
            else:
                # Use JWT-based auth (legacy)
                return self._make_request(
                    "POST",
                    "user_onboarding",
                    create_data,
                    user_token=user_token,
                )
        else:
            # Update existing record
            if user_token is None:
                # Use service client for session-based auth
                try:
                    result = (
                        self.service_client.table("user_onboarding")
                        .update(update_data)
                        .eq("id", user_id)
                        .execute()
                    )
                    if result.data:
                        return {"success": True, "data": result.data}
                    else:
                        return {
                            "success": False,
                            "error": "Failed to update onboarding record",
                        }
                except Exception as e:
                    logger.error(
                        f"Failed to update onboarding step via service client: {str(e)}"
                    )
                    return {"success": False, "error": str(e)}
            else:
                # Use JWT-based auth (legacy)
                return self._make_request(
                    "PATCH",
                    f"user_onboarding?id=eq.{user_id}",
                    update_data,
                    user_token=user_token,
                )

    def mark_podcast_claim_completed(
        self, user_id: str, user_token: str, podcast_title: str = None
    ) -> Dict:
        """Mark podcast claim step as completed and update user onboarding"""
        update_data = {
            "podcast_claim_completed": True,
            "has_verified_podcast_claims": True,
        }

        # Add podcast title if provided
        if podcast_title:
            update_data["claimed_podcast_title"] = podcast_title

        return self._make_request(
            "PATCH",
            f"user_onboarding?id=eq.{user_id}",
            update_data,
            user_token=user_token,
        )

    # Podcast claim methods
    def create_podcast_claim(
        self,
        user_id: str,
        listennotes_id: str,
        podcast_title: str,
        user_token: str = None,
        podcast_email: str = None,
        verification_code: str = None,
        expiry_hours: int = 24,
    ) -> Dict:
        """Create podcast claim with verification code expiry"""
        from datetime import datetime, timedelta, timezone

        # Calculate expiry time
        expiry_time = datetime.now(timezone.utc) + timedelta(
            hours=expiry_hours
        )

        data = {
            "user_id": user_id,
            "listennotes_id": listennotes_id,
            "podcast_title": podcast_title,
            "podcast_email": podcast_email,
            "verification_code": verification_code,
            "verification_code_expires_at": expiry_time.isoformat(),
        }

        # Use service client if no user token provided (session-based auth)
        if user_token is None:
            try:
                if not self.service_client:
                    return {
                        "success": False,
                        "error": "Service client not initialized",
                    }

                result = (
                    self.service_client.table("podcast_claims")
                    .insert(data)
                    .execute()
                )

                if result.data:
                    return {
                        "success": True,
                        "data": result.data,
                        "claim_id": result.data[0]["id"],
                    }
                else:
                    return {
                        "success": False,
                        "error": "Failed to create podcast claim",
                    }
            except Exception as e:
                logger.error(
                    f"Failed to create podcast claim via service client: {str(e)}"
                )
                return {"success": False, "error": str(e)}
        else:
            # Use user token for JWT-based auth (legacy)
            return self._make_request(
                "POST", "podcast_claims", data, user_token=user_token
            )

    def verify_podcast_claim(
        self, claim_id: str, verification_code: str, user_token: str
    ) -> Dict:
        """Verify podcast claim with code"""
        # First get the claim - this will respect RLS and only return user's own claims
        claim_result = self._make_request(
            "GET", f"podcast_claims?id=eq.{claim_id}", user_token=user_token
        )

        if not claim_result["success"] or not claim_result["data"]:
            return {"success": False, "error": "Claim not found"}

        claim = claim_result["data"][0]

        if claim["verification_code"] != verification_code:
            return {"success": False, "error": "Invalid verification code"}

        # Check if verification code has expired
        if claim.get("verification_code_expires_at"):
            from datetime import datetime, timezone

            expiry_time = datetime.fromisoformat(
                claim["verification_code_expires_at"].replace("Z", "+00:00")
            )
            if datetime.now(timezone.utc) > expiry_time:
                return {
                    "success": False,
                    "error": "Verification code has expired",
                }

        # Update claim as verified
        update_data = {
            "is_verified": True,
            "claim_status": "verified",
            "verified_at": "now()",
        }

        return self._make_request(
            "PATCH",
            f"podcast_claims?id=eq.{claim_id}",
            update_data,
            user_token=user_token,
        )

    def verify_podcast_claim_by_email(
        self, user_id: str, verification_code: str
    ) -> Dict:
        """Verify podcast claim using just verification code (no claim_id needed)"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Find the most recent pending claim for this user with this verification code
            result = (
                self.service_client.table("podcast_claims")
                .select("*")
                .eq("user_id", user_id)
                .eq("verification_code", verification_code)
                .eq("is_verified", False)
                .eq("claim_status", "pending")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if not result.data:
                return {
                    "success": False,
                    "error": "Invalid verification code or no pending claims found",
                }

            claim = result.data[0]

            # Check if verification code has expired
            if claim.get("verification_code_expires_at"):
                from datetime import datetime, timezone

                expiry_time = datetime.fromisoformat(
                    claim["verification_code_expires_at"].replace(
                        "Z", "+00:00"
                    )
                )
                if datetime.now(timezone.utc) > expiry_time:
                    return {
                        "success": False,
                        "error": "Verification code has expired",
                    }

            # Update claim as verified
            update_result = (
                self.service_client.table("podcast_claims")
                .update(
                    {
                        "is_verified": True,
                        "claim_status": "verified",
                        "verified_at": "now()",
                    }
                )
                .eq("id", claim["id"])
                .execute()
            )

            # Import the podcast into the main podcasts table
            if update_result.data:
                try:
                    self._import_claimed_podcast_to_main_table(claim)
                    logger.info(
                        f"Successfully imported claimed podcast '{claim.get('podcast_title')}' to main podcasts table"
                    )
                except Exception as import_error:
                    logger.error(
                        f"Failed to import claimed podcast to main table: {import_error}"
                    )
                    # Don't fail the verification if import fails

            if update_result.data:
                return {
                    "success": True,
                    "data": update_result.data[0],
                    "claim_id": claim["id"],
                    "podcast_title": claim["podcast_title"],
                }
            else:
                return {"success": False, "error": "Failed to verify claim"}

        except Exception as e:
            logger.error(f"Error verifying podcast claim by email: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_user_podcast_claims(self, user_id: str, user_token: str) -> Dict:
        """Get user's podcast claims"""
        return self._make_request(
            "GET",
            f"podcast_claims?user_id=eq.{user_id}",
            user_token=user_token,
        )

    def get_user_podcast_claims_session(self, user_id: str) -> Dict:
        """Get user's podcast claims using session-based auth"""
        try:
            if not self.service_client:
                return {
                    "success": False,
                    "error": "Service client not initialized",
                }

            result = (
                self.service_client.table("podcast_claims")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )

            if result.data is not None:
                return {"success": True, "data": result.data}
            else:
                return {
                    "success": False,
                    "error": "Failed to get podcast claims",
                }
        except Exception as e:
            logger.error(
                f"Failed to get podcast claims via service client: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def get_user_claimed_podcast_id(self, user_id: str) -> Optional[str]:
        """Get the user's claimed and verified podcast ID from the main podcasts table"""
        try:
            if not self.service_client:
                return None

            # First get the user's verified podcast claim
            claims_result = (
                self.service_client.table("podcast_claims")
                .select("listennotes_id")
                .eq("user_id", user_id)
                .eq("is_verified", True)
                .eq("claim_status", "verified")
                .limit(1)
                .execute()
            )

            if not claims_result.data:
                return None

            listennotes_id = claims_result.data[0]["listennotes_id"]

            # Now get the podcast ID from the main podcasts table
            podcast_result = (
                self.service_client.table("podcasts")
                .select("id")
                .eq("listennotes_id", listennotes_id)
                .single()
                .execute()
            )

            if podcast_result.data:
                return podcast_result.data["id"]

            return None

        except Exception as e:
            logger.error(f"Error getting user's claimed podcast ID: {str(e)}")
            return None

    def check_podcast_already_claimed(
        self, listennotes_id: str, current_user_id: str = None
    ) -> Dict:
        """Check if a podcast has already been claimed by any user"""
        try:
            if not self.service_client:
                return {
                    "success": False,
                    "error": "Service client not initialized",
                }

            # Use service client to bypass RLS and check all claims
            result = (
                self.service_client.table("podcast_claims")
                .select("*")
                .eq("listennotes_id", listennotes_id)
                .eq("is_verified", True)
                .execute()
            )

            if result.data is not None:
                is_claimed = len(result.data) > 0
                claimed_by_current_user = False

                if is_claimed and current_user_id:
                    # Check if current user is the one who claimed it
                    for claim in result.data:
                        if claim.get("user_id") == current_user_id:
                            claimed_by_current_user = True
                            break

                return {
                    "success": True,
                    "claimed": is_claimed,
                    "claimed_by_current_user": claimed_by_current_user,
                    "claim_data": result.data[0] if result.data else None,
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to check claim status",
                }

        except Exception as e:
            logger.error(f"Error checking podcast claim status: {str(e)}")
            return {"success": False, "error": str(e)}

    def check_user_signup_confirmed(self, user_id: str) -> Dict:
        """Check if user has confirmed their signup"""
        try:
            if not self.service_client:
                return {
                    "success": False,
                    "error": "Service client not initialized",
                }

            result = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .eq("user_id", user_id)
                .eq("signup_confirmed", True)
                .execute()
            )

            if result.data is not None:
                is_confirmed = len(result.data) > 0
                return {
                    "success": True,
                    "is_confirmed": is_confirmed,
                    "data": result.data[0] if result.data else None,
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to check signup status",
                }

        except Exception as e:
            logger.error(f"Error checking signup confirmation: {str(e)}")
            return {"success": False, "error": str(e)}

    # User Signup Tracking Methods
    def create_signup_tracking(
        self, user_id: str, email: str, name: str = None
    ) -> Dict:
        """Create a signup tracking record"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            tracking_data = {
                "user_id": user_id,
                "email": email,
                "name": name,
                "signup_at": "now()",
                "has_logged_in": False,
                "reminder_sent": False,
            }

            result = (
                self.service_client.table("user_signup_tracking")
                .insert(tracking_data)
                .execute()
            )

            if result.data:
                logger.info(f"Created signup tracking for user {user_id}")
                return {"success": True, "data": result.data}
            else:
                logger.error(f"Failed to create signup tracking: {result}")
                return {
                    "success": False,
                    "error": "Failed to create tracking record",
                }

        except Exception as e:
            logger.error(f"Error creating signup tracking: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_signup_tracking_by_user_id(self, user_id: str) -> Dict:
        """Get signup tracking record by user ID"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {"success": True, "data": None}
        except Exception as e:
            logger.error(f"Error getting signup tracking: {str(e)}")
            return {"success": False, "error": str(e)}

    def mark_signup_confirmed(self, user_id: str) -> Dict:
        """Mark user's signup as confirmed (either via magic link or manual code)"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # First, let's see what the current record looks like
            existing = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )

            if not existing.data:
                logger.error(f"No tracking record found for user {user_id}")
                return {"success": False, "error": "No tracking record found"}

            current_record = existing.data[0]
            current_confirmed = current_record.get("signup_confirmed")
            logger.info(
                f"User {user_id} current signup_confirmed value: {current_confirmed} (type: {type(current_confirmed)})"
            )

            # If already confirmed, don't update
            if current_confirmed == True:
                logger.info(
                    f"User {user_id} already marked as signup confirmed"
                )
                return {"success": True, "message": "User already confirmed"}

            # Update only if signup_confirmed is False (not True)
            result = (
                self.service_client.table("user_signup_tracking")
                .update(
                    {"signup_confirmed": True, "signup_confirmed_at": "now()"}
                )
                .eq("user_id", user_id)
                .eq("signup_confirmed", False)
                .execute()
            )

            logger.info(f"Update result for user {user_id}: {result.data}")

            if result.data:
                logger.info(
                    f"Successfully marked signup confirmed for user {user_id}"
                )

                # Ensure user has proper defaults when confirming signup
                self.ensure_user_defaults(user_id)

                return {"success": True, "data": result.data}
            else:
                # The update didn't affect any rows - let's check why
                check_again = (
                    self.service_client.table("user_signup_tracking")
                    .select("*")
                    .eq("user_id", user_id)
                    .execute()
                )
                if check_again.data:
                    record_after = check_again.data[0]
                    logger.error(
                        f"Update failed for user {user_id}. Record after attempt: {record_after}"
                    )
                else:
                    logger.error(f"Record disappeared for user {user_id}")
                return {"success": False, "error": "Update affected no rows"}

        except Exception as e:
            logger.error(f"Error marking signup confirmed: {str(e)}")
            return {"success": False, "error": str(e)}

    def mark_first_login(self, user_id: str) -> Dict:
        """Mark user's first login"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Update only if hasn't logged in before
            result = (
                self.service_client.table("user_signup_tracking")
                .update({"has_logged_in": True, "first_login_at": "now()"})
                .eq("user_id", user_id)
                .eq("has_logged_in", False)
                .execute()
            )

            if result.data:
                logger.info(f"Marked first login for user {user_id}")
                return {"success": True, "data": result.data}
            else:
                # Check if user already logged in
                existing = (
                    self.service_client.table("user_signup_tracking")
                    .select("*")
                    .eq("user_id", user_id)
                    .execute()
                )
                if existing.data and existing.data[0].get("has_logged_in"):
                    logger.info(f"User {user_id} already marked as logged in")
                    return {
                        "success": True,
                        "message": "User already logged in",
                    }
                else:
                    logger.warning(
                        f"No tracking record found for user {user_id}"
                    )
                    return {
                        "success": False,
                        "error": "No tracking record found",
                    }

        except Exception as e:
            logger.error(f"Error marking first login: {str(e)}")
            return {"success": False, "error": str(e)}

    def update_last_sign_in_at(self, user_id: str) -> Dict:
        """Update user's last_sign_in_at timestamp in auth.users table"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            from datetime import datetime, timezone

            # Use RPC to update auth.users table directly
            # This requires a database function - we'll use raw SQL via the REST API
            result = self.service_client.rpc(
                "update_user_last_sign_in", {"user_id_input": user_id}
            ).execute()

            if result:
                logger.info(f"Updated last_sign_in_at for user {user_id}")
                return {"success": True}
            else:
                logger.warning(
                    f"Failed to update last_sign_in_at for user {user_id}"
                )
                return {
                    "success": False,
                    "error": "Failed to update last_sign_in_at",
                }

        except Exception as e:
            # If the function doesn't exist, log but don't fail
            logger.warning(
                f"Could not update last_sign_in_at for user {user_id}: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def get_users_needing_reminder(self, hours_since_signup: int = 24) -> Dict:
        """Get users who need first login reminders"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Calculate cutoff time
            from datetime import datetime, timedelta, timezone

            cutoff_time = datetime.now(timezone.utc) - timedelta(
                hours=hours_since_signup
            )
            cutoff_iso = cutoff_time.isoformat()

            result = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .lt("signup_at", cutoff_iso)
                .eq("has_logged_in", False)
                .eq("reminder_sent", False)
                .execute()
            )

            if result.data is not None:
                logger.info(
                    f"Found {len(result.data)} users needing reminders"
                )
                return {"success": True, "data": result.data}
            else:
                logger.error(f"Failed to get users needing reminder: {result}")
                return {"success": False, "error": "Failed to query users"}

        except Exception as e:
            logger.error(f"Error getting users needing reminder: {str(e)}")
            return {"success": False, "error": str(e)}

    def mark_reminder_sent(self, user_id: str) -> Dict:
        """Mark reminder as sent for a user"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("user_signup_tracking")
                .update({"reminder_sent": True, "reminder_sent_at": "now()"})
                .eq("user_id", user_id)
                .execute()
            )

            if result.data:
                logger.info(f"Marked reminder sent for user {user_id}")
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to mark reminder sent for user {user_id}"
                )
                return {
                    "success": False,
                    "error": "Failed to update reminder status",
                }

        except Exception as e:
            logger.error(f"Error marking reminder sent: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_users_needing_confirmation_sync(self) -> Dict:
        """Get users who have confirmed signup but haven't been synced to Customer.io"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .eq("signup_confirmed", True)
                .eq("confirmation_synced_to_customerio", False)
                .execute()
            )

            if result.data is not None:
                logger.info(
                    f"Found {len(result.data)} users needing confirmation sync"
                )
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to get users needing confirmation sync: {result}"
                )
                return {"success": False, "error": "Failed to query users"}

        except Exception as e:
            logger.error(
                f"Error getting users needing confirmation sync: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def mark_confirmation_synced_to_customerio(self, user_id: str) -> Dict:
        """Mark that user's confirmation has been synced to Customer.io"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("user_signup_tracking")
                .update(
                    {
                        "confirmation_synced_to_customerio": True,
                        "confirmation_synced_at": "now()",
                    }
                )
                .eq("user_id", user_id)
                .execute()
            )

            if result.data:
                logger.info(
                    f"Marked confirmation synced to Customer.io for user {user_id}"
                )
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to mark confirmation synced for user {user_id}"
                )
                return {
                    "success": False,
                    "error": "Failed to update sync status",
                }

        except Exception as e:
            logger.error(f"Error marking confirmation synced: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_signup_stats(self) -> Dict:
        """Get signup and login statistics"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Get all records
            all_users = (
                self.service_client.table("user_signup_tracking")
                .select("*")
                .execute()
            )

            if all_users.data is None:
                return {"success": False, "error": "Failed to fetch stats"}

            total_signups = len(all_users.data)
            users_logged_in = len(
                [u for u in all_users.data if u.get("has_logged_in")]
            )
            users_not_logged_in = total_signups - users_logged_in
            reminders_sent = len(
                [u for u in all_users.data if u.get("reminder_sent")]
            )

            # Users needing reminder (signed up >24h ago, not logged in, no reminder sent)
            from datetime import datetime, timedelta, timezone

            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

            users_needing_reminder = 0
            for user in all_users.data:
                signup_time = datetime.fromisoformat(
                    user["signup_at"].replace("Z", "+00:00")
                )
                if (
                    signup_time <= cutoff_time
                    and not user.get("has_logged_in")
                    and not user.get("reminder_sent")
                ):
                    users_needing_reminder += 1

            stats = {
                "total_signups": total_signups,
                "users_logged_in": users_logged_in,
                "users_not_logged_in": users_not_logged_in,
                "reminders_sent": reminders_sent,
                "users_needing_reminder": users_needing_reminder,
            }

            logger.info(f"Signup stats: {stats}")
            return {"success": True, "data": stats}

        except Exception as e:
            logger.error(f"Error getting signup stats: {str(e)}")
            return {"success": False, "error": str(e)}

    # Subscription Management Methods
    def get_user_subscription(self, user_id: str) -> Dict:
        """Get user's current subscription"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Use the database function to get subscription with plan details
            result = self.service_client.rpc(
                "get_user_subscription_plan", {"input_user_id": user_id}
            ).execute()

            if result.data:
                subscription_data = result.data[0]

                # Get additional plan details
                plan_result = (
                    self.service_client.table("subscription_plans")
                    .select("*")
                    .eq("id", subscription_data["plan_id"])
                    .single()
                    .execute()
                )

                if plan_result.data:
                    return {
                        "success": True,
                        "data": {
                            "plan": {
                                **plan_result.data,
                                "status": subscription_data["status"],
                                "is_premium": subscription_data["is_premium"],
                            }
                        },
                    }

            return {"success": False, "error": "No subscription found"}

        except Exception as e:
            logger.error(f"Error getting user subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def create_subscription(
        self,
        user_id: str,
        plan_name: str,
        stripe_customer_id: str = None,
        stripe_subscription_id: str = None,
    ) -> Dict:
        """Create a new subscription for user"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Get plan ID
            plan_result = (
                self.service_client.table("subscription_plans")
                .select("id")
                .eq("name", plan_name)
                .execute()
            )

            if not plan_result.data or len(plan_result.data) == 0:
                logger.error(
                    f"Subscription plan '{plan_name}' not found in database"
                )
                return {
                    "success": False,
                    "error": f"Plan '{plan_name}' not found",
                }

            plan_id = plan_result.data[0]["id"]

            # Create subscription
            from datetime import datetime, timedelta, timezone

            subscription_data = {
                "user_id": user_id,
                "plan_id": plan_id,
                "status": "active",
                "starts_at": datetime.now(timezone.utc).isoformat(),
            }

            if stripe_customer_id:
                subscription_data["stripe_customer_id"] = stripe_customer_id
            if stripe_subscription_id:
                subscription_data["stripe_subscription_id"] = (
                    stripe_subscription_id
                )

            # If paid plan, set end date to 1 month from now
            if plan_name != "free":
                subscription_data["ends_at"] = (
                    datetime.now(timezone.utc) + timedelta(days=30)
                ).isoformat()

            # Delete existing subscription first (since we have UNIQUE constraint)
            self.service_client.table("user_subscriptions").delete().eq(
                "user_id", user_id
            ).execute()

            # Insert new subscription
            result = (
                self.service_client.table("user_subscriptions")
                .insert(subscription_data)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {
                    "success": False,
                    "error": "Failed to create subscription",
                }

        except Exception as e:
            logger.error(f"Error creating subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def update_subscription_status(self, user_id: str, status: str) -> Dict:
        """Update subscription status"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            update_data = {"status": status}

            if status == "cancelled":
                update_data["cancelled_at"] = datetime.now().isoformat()

            result = (
                self.service_client.table("user_subscriptions")
                .update(update_data)
                .eq("user_id", user_id)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {
                    "success": False,
                    "error": "Failed to update subscription",
                }

        except Exception as e:
            logger.error(f"Error updating subscription status: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_subscription_plans(self) -> Dict:
        """Get all available subscription plans"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("subscription_plans")
                .select("*")
                .eq("is_active", True)
                .order("price_monthly")
                .execute()
            )

            if result.data is not None:
                return {"success": True, "data": result.data}
            else:
                return {
                    "success": False,
                    "error": "Failed to get subscription plans",
                }

        except Exception as e:
            logger.error(f"Error getting subscription plans: {str(e)}")
            return {"success": False, "error": str(e)}

    def ensure_user_defaults(self, user_id: str) -> Dict:
        """Ensure user has default role and subscription assigned"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Check and assign default role if missing
            role_result = (
                self.service_client.table("user_roles")
                .select("role")
                .eq("user_id", user_id)
                .execute()
            )

            if not role_result.data:
                logger.info(f"Assigning default role to user {user_id}")
                role_assign_result = self.assign_user_role(
                    user_id, "podcaster", granted_by=None
                )
                if not role_assign_result["success"]:
                    logger.error(
                        f"Failed to assign default role to user {user_id}"
                    )

            # Check and assign default subscription if missing
            subscription_result = (
                self.service_client.table("user_subscriptions")
                .select("plan_id")
                .eq("user_id", user_id)
                .execute()
            )

            if not subscription_result.data:
                logger.info(
                    f"Assigning default subscription to user {user_id}"
                )
                subscription_assign_result = self.create_subscription(
                    user_id, "free"
                )
                if not subscription_assign_result["success"]:
                    logger.error(
                        f"Failed to assign default subscription to user {user_id}"
                    )

            return {"success": True, "message": "User defaults ensured"}

        except Exception as e:
            logger.error(f"Error ensuring user defaults: {str(e)}")
            return {"success": False, "error": str(e)}

    def assign_user_role(
        self, user_id: str, role: str, granted_by: str = None
    ) -> Dict:
        """Assign a role to a user"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            role_data = {
                "user_id": user_id,
                "role": role,
                "granted_by": granted_by,
                "is_active": True,
            }

            # Delete existing role first
            self.service_client.table("user_roles").delete().eq(
                "user_id", user_id
            ).execute()

            # Insert new role
            result = (
                self.service_client.table("user_roles")
                .insert(role_data)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {"success": False, "error": "Failed to assign role"}

        except Exception as e:
            logger.error(f"Error assigning user role: {str(e)}")
            return {"success": False, "error": str(e)}

    # Podcast Claim Reminder Methods
    def get_podcast_claims_needing_reminder(
        self, hours_since_created: int = 24
    ) -> Dict:
        """Get podcast claims that need reminders (unverified and no reminder sent yet)"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Calculate cutoff time
            from datetime import datetime, timedelta, timezone

            cutoff_time = datetime.now(timezone.utc) - timedelta(
                hours=hours_since_created
            )
            cutoff_iso = cutoff_time.isoformat()

            result = (
                self.service_client.table("podcast_claims")
                .select("*")
                .lt("created_at", cutoff_iso)
                .eq("is_verified", False)
                .eq("reminder_sent", False)
                .eq("claim_status", "pending")
                .execute()
            )

            if result.data is not None:
                logger.info(
                    f"Found {len(result.data)} podcast claims needing reminders"
                )
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to get claims needing reminder: {result}"
                )
                return {"success": False, "error": "Failed to query claims"}

        except Exception as e:
            logger.error(f"Error getting claims needing reminder: {str(e)}")
            return {"success": False, "error": str(e)}

    def mark_podcast_claim_reminder_sent(self, claim_id: str) -> Dict:
        """Mark reminder as sent for a podcast claim"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table("podcast_claims")
                .update({"reminder_sent": True, "reminder_sent_at": "now()"})
                .eq("id", claim_id)
                .execute()
            )

            if result.data:
                logger.info(f"Marked reminder sent for claim {claim_id}")
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to mark reminder sent for claim {claim_id}"
                )
                return {
                    "success": False,
                    "error": "Failed to update reminder status",
                }

        except Exception as e:
            logger.error(f"Error marking reminder sent: {str(e)}")
            return {"success": False, "error": str(e)}

    def update_podcast_claim_verification_code(
        self, claim_id: str, new_code: str, expiry_hours: int = 24
    ) -> Dict:
        """Update podcast claim with new verification code and expiry"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            from datetime import datetime, timedelta, timezone

            expiry_time = datetime.now(timezone.utc) + timedelta(
                hours=expiry_hours
            )

            result = (
                self.service_client.table("podcast_claims")
                .update(
                    {
                        "verification_code": new_code,
                        "verification_code_expires_at": expiry_time.isoformat(),
                    }
                )
                .eq("id", claim_id)
                .execute()
            )

            if result.data:
                logger.info(f"Updated verification code for claim {claim_id}")
                return {"success": True, "data": result.data}
            else:
                logger.error(
                    f"Failed to update verification code for claim {claim_id}"
                )
                return {
                    "success": False,
                    "error": "Failed to update verification code",
                }

        except Exception as e:
            logger.error(f"Error updating verification code: {str(e)}")
            return {"success": False, "error": str(e)}

    # Podcast Categories Methods
    def get_active_podcast_categories(self) -> Dict:
        """Get all active podcast categories using service role (public data)"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Use service client for public category data (bypasses RLS)
            result = (
                self.service_client.table("podcast_categories")
                .select("*")
                .eq("is_active", True)
                .order("sort_order")
                .execute()
            )

            if result.data is not None:
                logger.info(
                    f"Retrieved {len(result.data)} active podcast categories"
                )
                return {"success": True, "data": result.data}
            else:
                logger.error(f"Failed to get podcast categories: {result}")
                return {
                    "success": False,
                    "error": "Failed to fetch categories",
                }

        except Exception as e:
            logger.error(f"Error getting podcast categories: {str(e)}")
            return {"success": False, "error": str(e)}

    # States and Countries Methods
    def get_states_countries(
        self,
        country_code: str = None,
        search: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict:
        """Get states and countries with optional filtering"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Supabase service client not initialized",
            }

        try:
            # Build query using service client to bypass RLS
            query = self.service_client.table("states_countries").select("*")

            # Apply filters
            if country_code:
                query = query.eq("country_code", country_code.upper())

            if search:
                # Search in state name or country name
                search_term = f"%{search}%"
                query = query.or_(
                    f"name.ilike.{search_term},country_name.ilike.{search_term}"
                )

            # Apply pagination and ordering (max 1000 records due to Supabase limit)
            query = (
                query.order("country_name")
                .order("name")
                .range(offset, offset + limit - 1)
            )

            result = query.execute()

            if result.data is not None:
                logger.info(f"Retrieved {len(result.data)} states/countries")
                return {"success": True, "data": result.data}
            else:
                logger.error(f"Failed to get states/countries: {result}")
                return {
                    "success": False,
                    "error": "Failed to fetch states and countries",
                }

        except Exception as e:
            logger.error(f"Error getting states/countries: {str(e)}")
            return {"success": False, "error": str(e)}

    def create_grant_application(self, application_data: Dict) -> Dict:
        """Create a new grant application in Supabase."""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Convert enum values to strings for Supabase
            # Convert all enums to their string values
            application_data["podcasting_experience"] = application_data[
                "podcasting_experience"
            ].value
            application_data["challenges"] = [
                c.value for c in application_data["challenges"]
            ]
            application_data["willing_to_share"] = application_data[
                "willing_to_share"
            ].value
            application_data["heard_about"] = application_data[
                "heard_about"
            ].value
            result = (
                self.service_client.table("grant_applications")
                .insert(application_data)
                .execute()
            )

            if result.data:
                logger.info(
                    f"Created grant application for {application_data.get('email')}"
                )
                return {"success": True, "data": result.data[0]}
            else:
                logger.error(f"Failed to create grant application: {result}")
                # Attempt to parse a more specific error
                try:
                    error_json = json.loads(result.get("error", "{}"))
                    error_message = error_json.get(
                        "message", "Failed to create grant application"
                    )
                    if "duplicate key" in error_message:
                        return {
                            "success": False,
                            "error": "An application with this email or podcast link already exists.",
                        }
                except (json.JSONDecodeError, AttributeError):
                    error_message = "Failed to create grant application"

                return {"success": False, "error": error_message}

        except Exception as e:
            logger.error(
                f"Error creating grant application in Supabase: {str(e)}"
            )
            if "duplicate key" in str(e).lower():
                return {
                    "success": False,
                    "error": "An application with this email or podcast link already exists.",
                }
            return {"success": False, "error": str(e)}

    # Waitlist methods (moved from SQLite to Supabase)
    def add_waitlist_email(
        self, email: str, first_name: str, last_name: str, variant: str
    ) -> Dict:
        """Add email to waitlist in Supabase"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            data = {
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "variant": variant,
                "customerio_sync_status": "pending",
            }

            result = (
                self.service_client.table("waitlist_emails")
                .insert(data)
                .execute()
            )

            if result.data:
                logger.info(f"Added email {email} to Supabase waitlist")
                return {"success": True, "data": result.data[0]}
            else:
                return {
                    "success": False,
                    "error": "Failed to add email to waitlist",
                }

        except Exception as e:
            logger.error(f"Failed to add waitlist email to Supabase: {str(e)}")
            if "duplicate key" in str(e).lower():
                return {
                    "success": False,
                    "error": "Email already exists in waitlist",
                }
            return {"success": False, "error": str(e)}

    def add_microgrant_waitlist_email(
        self, email: str, first_name: str, last_name: str
    ) -> Dict:
        """Add email to microgrant waitlist in Supabase"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            data = {
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "customerio_sync_status": "pending",
            }

            result = (
                self.service_client.table("microgrant_waitlist_emails")
                .insert(data)
                .execute()
            )

            if result.data:
                logger.info(
                    f"Added email {email} to Supabase microgrant waitlist"
                )
                return {"success": True, "data": result.data[0]}
            else:
                return {
                    "success": False,
                    "error": "Failed to add email to microgrant waitlist",
                }

        except Exception as e:
            logger.error(
                f"Failed to add microgrant waitlist email to Supabase: {str(e)}"
            )
            if "duplicate key" in str(e).lower():
                return {
                    "success": False,
                    "error": "Email already exists in microgrant waitlist",
                }
            return {"success": False, "error": str(e)}

    def update_customerio_sync_status(
        self,
        table_name: str,
        record_id: int,
        status: str,
        increment_attempts: bool = False,
    ) -> Dict:
        """Update Customer.io sync status for a waitlist record"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            update_data = {
                "customerio_sync_status": status,
                "last_sync_attempt_at": "now()",
            }

            if increment_attempts:
                # Get current attempts count and increment
                current_record = (
                    self.service_client.table(table_name)
                    .select("customerio_sync_attempts")
                    .eq("id", record_id)
                    .execute()
                )
                if current_record.data:
                    current_attempts = current_record.data[0].get(
                        "customerio_sync_attempts", 0
                    )
                    update_data["customerio_sync_attempts"] = (
                        current_attempts + 1
                    )

            result = (
                self.service_client.table(table_name)
                .update(update_data)
                .eq("id", record_id)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {
                    "success": False,
                    "error": "Failed to update sync status",
                }

        except Exception as e:
            logger.error(f"Failed to update Customer.io sync status: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_unsynced_waitlist_entries(
        self, table_name: str = "waitlist_emails", retry_limit: int = 5
    ) -> Dict:
        """Get waitlist entries that need Customer.io sync"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            result = (
                self.service_client.table(table_name)
                .select("*")
                .in_("customerio_sync_status", ["pending", "failed"])
                .lt("customerio_sync_attempts", retry_limit)
                .order("created_at")
                .execute()
            )

            if result.data is not None:
                return {"success": True, "data": result.data}
            else:
                return {
                    "success": False,
                    "error": "Failed to get unsynced entries",
                }

        except Exception as e:
            logger.error(f"Failed to get unsynced waitlist entries: {str(e)}")
            return {"success": False, "error": str(e)}

    def update_favorite_podcast_metadata(
        self,
        podcast_id: str,
        title: str,
        image: str = None,
        publisher: str = None,
    ) -> Dict:
        """
        DEPRECATED: This method is no longer used.

        Previously updated denormalized metadata in user_favorite_podcasts table,
        but that table has been deprecated in favor of user_podcast_follows which
        gets podcast metadata dynamically via JOINs with the podcasts table.

        Keeping this method as a no-op for backward compatibility.
        """
        logger.debug(
            f"update_favorite_podcast_metadata called for {podcast_id} but is deprecated - skipping"
        )
        return {
            "success": True,
            "message": "Method deprecated, no action taken",
        }

    def _sync_onboarding_to_profile(self, user_id: str) -> Dict:
        """
        Sync onboarding data to user_profiles table when onboarding completes.
        This ensures location and name data is available in the profile.
        """
        try:
            # Get onboarding data
            onboarding_result = (
                self.service_client.table("user_onboarding")
                .select("location_id")
                .eq("id", user_id)
                .execute()
            )

            if not onboarding_result.data:
                return {"success": False, "error": "No onboarding data found"}

            onboarding_data = onboarding_result.data[0]
            location_id = onboarding_data.get("location_id")

            # If there's a location_id, convert it to location string (City, Country)
            location_string = None
            if location_id:
                try:
                    # Get location data from states_countries table
                    location_result = (
                        self.service_client.table("states_countries")
                        .select("name, country_name")
                        .eq("id", location_id)
                        .execute()
                    )

                    if location_result.data:
                        state_name = location_result.data[0].get("name")
                        country_name = location_result.data[0].get(
                            "country_name"
                        )

                        # Format as "City, Country"
                        if state_name and country_name:
                            location_string = f"{state_name}, {country_name}"
                        elif state_name:
                            location_string = state_name
                except Exception as e:
                    logger.warning(
                        f"Could not fetch location for id {location_id}: {e}"
                    )

            # Get user's name from auth.users metadata
            first_name = None
            last_name = None
            try:
                user_data = self.service_client.auth.admin.get_user_by_id(user_id)
                if user_data and hasattr(user_data, 'user') and user_data.user.user_metadata:
                    first_name = user_data.user.user_metadata.get('first_name')
                    last_name = user_data.user.user_metadata.get('last_name')
            except Exception as e:
                logger.warning(f"Could not fetch user metadata for {user_id}: {e}")

            # Prepare update data
            profile_update = {}
            if location_string:
                profile_update["location"] = location_string
            if first_name:
                profile_update["first_name"] = first_name
            if last_name:
                profile_update["last_name"] = last_name

            # Only update if there's data to update
            if not profile_update:
                logger.info(
                    f"No onboarding data to sync to profile for user {user_id}"
                )
                return {"success": True, "message": "No data to sync"}

            # Check if profile exists
            existing_profile = (
                self.service_client.table("user_profiles")
                .select("id")
                .eq("user_id", user_id)
                .execute()
            )

            if existing_profile.data:
                # Update existing profile
                result = (
                    self.service_client.table("user_profiles")
                    .update(profile_update)
                    .eq("user_id", user_id)
                    .execute()
                )

                if not result.data:
                    return {
                        "success": False,
                        "error": "Failed to update profile",
                    }

                logger.info(
                    f"Synced onboarding data to profile for user {user_id}: {profile_update}"
                )
            else:
                # Create new profile
                profile_update["user_id"] = user_id
                result = (
                    self.service_client.table("user_profiles")
                    .insert(profile_update)
                    .execute()
                )

                if not result.data:
                    return {
                        "success": False,
                        "error": "Failed to create profile",
                    }

                logger.info(
                    f"Created profile with onboarding data for user {user_id}: {profile_update}"
                )

            return {"success": True, "data": result.data}

        except Exception as e:
            logger.error(
                f"Error syncing onboarding to profile for user {user_id}: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    def _import_podcast_from_listennotes(
        self, listennotes_id: str
    ) -> Optional[str]:
        """
        Import a podcast from ListenNotes API into the local database

        Args:
            listennotes_id: The ListenNotes podcast ID

        Returns:
            The local podcast ID if successful, None otherwise
        """
        try:
            from listennotes_client import ListenNotesClient

            # Fetch podcast data from ListenNotes
            ln_client = ListenNotesClient()
            if not ln_client.client:
                logger.warning(
                    "ListenNotes API client not initialized, cannot import podcast"
                )
                return None

            result = ln_client.get_podcast_by_id(listennotes_id)

            if (
                not result
                or not result.get("success")
                or not result.get("data")
            ):
                logger.warning(
                    f"Could not fetch podcast {listennotes_id} from ListenNotes"
                )
                return None

            podcast_data = result["data"]

            # Prepare insert data
            insert_data = {
                "listennotes_id": listennotes_id,
                "title": podcast_data.get("title", "Unknown Podcast"),
                "description": podcast_data.get("description", ""),
                "publisher": podcast_data.get("publisher", ""),
                "language": podcast_data.get("language", "en"),
                "image_url": podcast_data.get("image", ""),
                "thumbnail_url": podcast_data.get("thumbnail", ""),
                "rss_url": podcast_data.get("rss", ""),
                "total_episodes": podcast_data.get("total_episodes", 0),
                "explicit_content": podcast_data.get(
                    "explicit_content", False
                ),
                "has_full_data": True,
            }

            # Insert into podcasts table
            insert_result = (
                self.service_client.table("podcasts")
                .insert(insert_data)
                .execute()
            )

            if not insert_result.data:
                logger.error(
                    f"Failed to insert podcast {listennotes_id} into database"
                )
                return None

            podcast_id = insert_result.data[0]["id"]
            logger.info(
                f"Successfully imported podcast '{podcast_data.get('title')}' (ID: {podcast_id}) from ListenNotes"
            )

            # Handle category mapping using first genre_id from ListenNotes
            try:
                genre_ids = podcast_data.get("genre_ids", [])
                if genre_ids and len(genre_ids) > 0:
                    first_genre_id = genre_ids[0]

                    # Look up PodGround category from genre mapping table
                    genre_mapping_result = (
                        self.service_client.table("category_genre")
                        .select("category_id")
                        .eq("genre_id", first_genre_id)
                        .limit(1)
                        .execute()
                    )

                    if genre_mapping_result.data:
                        category_id = genre_mapping_result.data[0][
                            "category_id"
                        ]

                        # Add the category mapping to the junction table
                        self.service_client.table(
                            "podcast_category_mappings"
                        ).insert(
                            [
                                {
                                    "podcast_id": podcast_id,
                                    "category_id": category_id,
                                }
                            ]
                        ).execute()

                        logger.info(
                            f"Mapped genre_id {first_genre_id} to category {category_id}"
                        )
            except Exception as cat_error:
                logger.warning(f"Could not add category mapping: {cat_error}")

            return podcast_id

        except Exception as e:
            logger.error(f"Error importing podcast {listennotes_id}: {e}")
            return None

    def _create_follows_from_onboarding(
        self,
        user_id: str,
        favorite_podcast_ids: List[str],
        automatic_favorites: List[Dict] = None,
    ) -> Dict:
        """Create follows from onboarding data - single source of truth in user_podcast_follows"""
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            follows_data = []
            valid_podcast_ids = []

            # Helper function to get valid podcast ID
            def get_valid_podcast_id(podcast_id: str) -> str:
                """Get a valid podcast ID, checking both id and listennotes_id fields, importing if needed"""
                try:
                    # First try direct ID lookup
                    result = (
                        self.service_client.table("podcasts")
                        .select("id")
                        .eq("id", podcast_id)
                        .execute()
                    )
                    if result.data:
                        return podcast_id

                    # Try listennotes_id lookup
                    result = (
                        self.service_client.table("podcasts")
                        .select("id")
                        .eq("listennotes_id", podcast_id)
                        .execute()
                    )
                    if result.data:
                        return result.data[0]["id"]

                    # Try featured_podcasts table by podcast_id (listennotes_id)
                    result = (
                        self.service_client.table("featured_podcasts")
                        .select("id")
                        .eq("podcast_id", podcast_id)
                        .execute()
                    )
                    if result.data:
                        return result.data[0]["id"]

                    # Podcast not found - try to import from ListenNotes
                    logger.info(
                        f"Podcast {podcast_id} not found locally, attempting to import from ListenNotes"
                    )
                    imported_id = self._import_podcast_from_listennotes(
                        podcast_id
                    )
                    if imported_id:
                        logger.info(
                            f"Successfully imported podcast {podcast_id} as {imported_id}"
                        )
                        return imported_id

                    logger.warning(
                        f"Podcast ID {podcast_id} not found in any table and could not be imported"
                    )
                    return None
                except Exception as e:
                    logger.error(
                        f"Error looking up podcast ID {podcast_id}: {e}"
                    )
                    return None

            # Add user-selected favorites
            for podcast_id in favorite_podcast_ids[:5]:  # Only take first 5
                valid_id = get_valid_podcast_id(podcast_id)
                if valid_id:
                    valid_podcast_ids.append(valid_id)
                    follows_data.append(
                        {
                            "user_id": user_id,
                            "podcast_id": valid_id,
                            "notification_enabled": True,
                        }
                    )
                else:
                    logger.warning(
                        f"Skipping invalid podcast ID from favorites: {podcast_id}"
                    )

            # Add automatic favorites if provided
            if automatic_favorites:
                for auto_fav in automatic_favorites:
                    if auto_fav.get("podcast_id"):
                        # Check if not already in user's selection
                        if auto_fav["podcast_id"] not in favorite_podcast_ids:
                            valid_id = get_valid_podcast_id(
                                auto_fav["podcast_id"]
                            )
                            if valid_id and valid_id not in valid_podcast_ids:
                                valid_podcast_ids.append(valid_id)
                                follows_data.append(
                                    {
                                        "user_id": user_id,
                                        "podcast_id": valid_id,
                                        "notification_enabled": True,
                                    }
                                )
                                logger.info(
                                    f"Adding auto-favorite podcast: {auto_fav.get('podcast_title', valid_id)}"
                                )
                            elif not valid_id:
                                logger.warning(
                                    f"Skipping invalid auto-favorite podcast ID: {auto_fav['podcast_id']} ({auto_fav.get('podcast_title', 'Unknown')})"
                                )

            if follows_data:
                # First, delete any existing follows for this user to avoid duplicates
                self.service_client.table("user_podcast_follows").delete().eq(
                    "user_id", user_id
                ).execute()

                # Insert the new follows
                result = (
                    self.service_client.table("user_podcast_follows")
                    .insert(follows_data)
                    .execute()
                )

                if result.data:
                    logger.info(
                        f"Created {len(follows_data)} podcast follows for user {user_id}"
                    )
                    return {"success": True, "data": result.data}
                else:
                    return {
                        "success": False,
                        "error": "Failed to create follows",
                    }
            else:
                logger.warning(
                    f"No valid podcast IDs found to create follows for user {user_id}"
                )

            return {"success": True, "data": []}

        except Exception as e:
            logger.error(f"Failed to create follows from favorites: {str(e)}")
            return {"success": False, "error": str(e)}

    def _import_claimed_podcast_to_main_table(self, claim: Dict) -> bool:
        """Import a verified claimed podcast into the main podcasts table"""
        try:
            listennotes_id = claim.get("listennotes_id")
            podcast_title = claim.get("podcast_title")

            if not listennotes_id or not podcast_title:
                logger.warning(
                    f"Missing required data for podcast import: listennotes_id={listennotes_id}, title={podcast_title}"
                )
                return False

            # Check if podcast already exists in main table
            existing_check = (
                self.service_client.table("podcasts")
                .select("id")
                .eq("listennotes_id", listennotes_id)
                .execute()
            )
            if existing_check.data:
                logger.info(
                    f"Podcast with ListenNotes ID {listennotes_id} already exists in main table"
                )
                return True

            # Try to get full podcast data from ListenNotes API if available
            try:
                from listennotes_client import ListenNotesClient
                import os

                listennotes_api_key = os.getenv("LISTENNOTES_API_KEY")
                if listennotes_api_key:
                    ln_client = ListenNotesClient(listennotes_api_key)
                    podcast_data = ln_client.get_podcast_by_id(listennotes_id)

                    if podcast_data:
                        # Insert with full data from ListenNotes
                        insert_data = {
                            "listennotes_id": listennotes_id,
                            "title": podcast_data.get("title", podcast_title),
                            "description": podcast_data.get("description", ""),
                            "publisher": podcast_data.get("publisher", ""),
                            "language": podcast_data.get("language", "en"),
                            "image_url": podcast_data.get("image", ""),
                            "thumbnail_url": podcast_data.get("thumbnail", ""),
                            "rss_url": podcast_data.get("rss", ""),
                            "total_episodes": podcast_data.get(
                                "total_episodes", 0
                            ),
                            "explicit_content": podcast_data.get(
                                "explicit_content", False
                            ),
                            "created_at": "now()",
                            "updated_at": "now()",
                        }
                    else:
                        raise Exception("Could not fetch from ListenNotes")
                else:
                    raise Exception("No ListenNotes API key")

            except Exception as ln_error:
                logger.warning(
                    f"Could not fetch full data from ListenNotes: {ln_error}, using minimal data"
                )

                # Get owner's name for publisher
                owner_name = None
                try:
                    user_id = claim.get("user_id")
                    if user_id:
                        from user_profile_service import UserProfileService
                        profile_service = UserProfileService()
                        import asyncio
                        owner_profile = asyncio.run(profile_service.get_user_profile(user_id))
                        if owner_profile and owner_profile.get("name"):
                            owner_name = owner_profile["name"]
                except Exception as name_error:
                    logger.warning(f"Could not get owner name: {name_error}")

                # Fallback to minimal data from claim
                insert_data = {
                    "listennotes_id": listennotes_id,
                    "title": podcast_title,
                    "description": "",
                    "publisher": owner_name or "",  # Empty string if no owner name
                    "language": "en",
                    "image_url": "",
                    "thumbnail_url": "",
                    "rss_url": "",
                    "total_episodes": 0,
                    "explicit_content": False,
                    "created_at": "now()",
                    "updated_at": "now()",
                }

            # Insert into podcasts table
            result = (
                self.service_client.table("podcasts")
                .insert(insert_data)
                .execute()
            )

            if result.data:
                podcast_id = result.data[0]["id"]
                logger.info(
                    f"Successfully imported claimed podcast '{podcast_title}' with ID {podcast_id}"
                )

                # Handle category mapping using first genre_id from ListenNotes
                try:
                    if (
                        "podcast_data" in locals()
                        and podcast_data
                        and "genre_ids" in podcast_data
                    ):
                        genre_ids = podcast_data.get("genre_ids", [])

                        if genre_ids and len(genre_ids) > 0:
                            # Take only the first genre_id
                            first_genre_id = genre_ids[0]
                            logger.info(
                                f"Mapping first genre_id {first_genre_id} to PodGround category"
                            )

                            # Look up PodGround category from genre mapping table
                            genre_mapping_result = (
                                self.service_client.table("category_genre")
                                .select("category_id")
                                .eq("genre_id", first_genre_id)
                                .limit(1)
                                .execute()
                            )

                            if genre_mapping_result.data:
                                category_id = genre_mapping_result.data[0][
                                    "category_id"
                                ]

                                # Add the category mapping to the junction table
                                mapping = {
                                    "podcast_id": podcast_id,
                                    "category_id": category_id,
                                }

                                mappings_result = (
                                    self.service_client.table(
                                        "podcast_category_mappings"
                                    )
                                    .insert([mapping])
                                    .execute()
                                )

                                if mappings_result.data:
                                    logger.info(
                                        f"Mapped genre_id {first_genre_id} to category {category_id} for claimed podcast"
                                    )
                                else:
                                    logger.warning(
                                        f"Failed to add category mapping for claimed podcast"
                                    )
                            else:
                                logger.warning(
                                    f"No PodGround category mapping found for genre_id {first_genre_id}"
                                )
                        else:
                            logger.info(
                                "No genre_ids available from ListenNotes for this podcast"
                            )

                except Exception as cat_error:
                    logger.warning(
                        f"Could not add category mapping for claimed podcast: {cat_error}"
                    )

                return True
            else:
                logger.error(
                    f"Failed to insert claimed podcast '{podcast_title}' into main table"
                )
                return False

        except Exception as e:
            logger.error(f"Error importing claimed podcast to main table: {e}")
            return False

    def is_user_platform_ready(self, user_id: str) -> Dict[str, Any]:
        """
        Check if user has completed onboarding AND has a verified podcast claim.
        Users must meet both criteria to be visible/messageable on the platform.

        Returns:
            Dict with 'success', 'is_ready', and optional 'reason' for why they're not ready
        """
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            # Check onboarding completion
            onboarding_result = (
                self.service_client.table("user_onboarding")
                .select("is_completed, step_5_completed")
                .eq("id", user_id)
                .execute()
            )

            if not onboarding_result.data:
                return {
                    "success": True,
                    "is_ready": False,
                    "reason": "onboarding_not_started",
                }

            onboarding = onboarding_result.data[0]
            if not onboarding.get("is_completed") or not onboarding.get(
                "step_5_completed"
            ):
                return {
                    "success": True,
                    "is_ready": False,
                    "reason": "onboarding_incomplete",
                }

            # Check verified podcast claim
            claim_result = (
                self.service_client.table("podcast_claims")
                .select("id, claim_status, is_verified")
                .eq("user_id", user_id)
                .eq("claim_status", "verified")
                .eq("is_verified", True)
                .execute()
            )

            if not claim_result.data:
                return {
                    "success": True,
                    "is_ready": False,
                    "reason": "podcast_not_claimed",
                }

            # User has completed onboarding and has verified podcast claim
            return {"success": True, "is_ready": True}

        except Exception as e:
            logger.error(
                f"Error checking if user {user_id} is platform ready: {e}"
            )
            return {"success": False, "error": str(e)}

    def filter_platform_ready_users(
        self, user_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Filter a list of user IDs to only include those who are platform ready.
        Batch operation for efficiency.

        Returns:
            Dict with 'success' and 'ready_user_ids' list
        """
        if not self.service_client:
            return {
                "success": False,
                "error": "Service client not initialized",
            }

        try:
            if not user_ids:
                return {"success": True, "ready_user_ids": []}

            # Get all onboarding statuses for these users
            onboarding_result = (
                self.service_client.table("user_onboarding")
                .select("id, is_completed, step_5_completed")
                .in_("id", user_ids)
                .execute()
            )

            # Filter to only completed onboarding
            completed_user_ids = set()
            for record in onboarding_result.data or []:
                if record.get("is_completed") and record.get(
                    "step_5_completed"
                ):
                    completed_user_ids.add(record["id"])

            if not completed_user_ids:
                return {"success": True, "ready_user_ids": []}

            # Get verified podcast claims for completed users
            claims_result = (
                self.service_client.table("podcast_claims")
                .select("user_id")
                .in_("user_id", list(completed_user_ids))
                .eq("claim_status", "verified")
                .eq("is_verified", True)
                .execute()
            )

            # Get unique user IDs with verified claims
            verified_user_ids = list(
                set(record["user_id"] for record in (claims_result.data or []))
            )

            return {"success": True, "ready_user_ids": verified_user_ids}

        except Exception as e:
            logger.error(f"Error filtering platform ready users: {e}")
            return {"success": False, "error": str(e)}


# Global instance and dependency function
_supabase_client = None


def get_supabase_client() -> SupabaseClient:
    """Get or create global Supabase client instance"""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
