from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Literal
from datetime import datetime
from enum import Enum

# Import post models
from post_models import *


class WaitlistRequest(BaseModel):
    name: str
    email: EmailStr
    variant: str  # "A" or "B"
    captcha_token: str


class WaitlistResponse(BaseModel):
    success: bool
    message: str


class MicrograntWaitlistRequest(BaseModel):
    name: str
    email: EmailStr
    captcha_token: str


class MicrograntWaitlistResponse(BaseModel):
    success: bool
    message: str


class ABVariantResponse(BaseModel):
    variant: str


class TokenResponse(BaseModel):
    token: str
    expires_in: int  # seconds


# Authentication Models
class SignUpRequest(BaseModel):
    name: str
    email: EmailStr


class SignInRequest(BaseModel):
    email: EmailStr


class ResendMagicLinkRequest(BaseModel):
    email: EmailStr


class CodeExchangeRequest(BaseModel):
    code: str
    state: Optional[str] = None


class CodeExchangeResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    redirect_url: Optional[str] = None  # Suggested redirect after success
    access_token: Optional[str] = None  # Session token for cross-origin auth


class AuthResponse(BaseModel):
    success: bool
    message: str
    user_id: Optional[str] = None
    access_token: Optional[str] = None
    magic_link: Optional[str] = None


# Podcast Models
class PodcastSearchResponse(BaseModel):
    id: str
    title: str
    description: str
    image: str
    publisher: str


class PodcastSearchResults(BaseModel):
    results: List[PodcastSearchResponse]
    total: int


class VerifyClaimByCodeRequest(BaseModel):
    verification_code: str


class ClaimResponse(BaseModel):
    success: bool
    message: str
    claim_id: Optional[str] = None


# Onboarding Models
class OnboardingRequest(BaseModel):
    podcasting_experience: str  # "0-1_year", "1-3_years", "3_years_plus"
    category_ids: List[str]  # Foreign keys to podcast_categories table (UUIDs)
    location_id: int  # Foreign key to states_countries table
    network_name: Optional[str] = None
    is_part_of_network: bool
    looking_for_guests: bool
    wants_to_be_guest: bool
    favorite_podcast_ids: List[str]


class OnboardingResponse(BaseModel):
    success: bool
    message: str


class CategoryResponse(BaseModel):
    categories: List[str]


class NetworkResponse(BaseModel):
    networks: List[str]


# Onboarding Status Models
class OnboardingStatusResponse(BaseModel):
    is_completed: bool
    current_step: int
    steps_completed: Dict[str, bool]
    has_pending_podcast_claims: bool
    has_verified_podcast_claims: bool


class OnboardingProfileResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    is_completed: bool
    current_step: int


# Podcast Claims Models
class PodcastClaimData(BaseModel):
    id: str
    listennotes_id: str
    podcast_title: str
    podcast_email: Optional[str]
    claim_status: str  # "pending", "verified", "failed"
    is_verified: bool
    created_at: str
    verified_at: Optional[str] = None


# Step-by-step onboarding models
class OnboardingStepRequest(BaseModel):
    step: int
    data: Dict


# Podcast Categories Models
class PodcastCategoryData(BaseModel):
    id: str  # UUID in database
    category_name: str
    apple_podcast_url: str
    active: bool
    image_url: Optional[str] = None


class PodcastCategoriesResponse(BaseModel):
    success: bool
    categories: List[PodcastCategoryData]


# RSS Feed Parser Models
class RSSFeedRequest(BaseModel):
    rss_url: str


class PodcastFeedInfo(BaseModel):
    title: str
    description: Optional[str] = None
    link: Optional[str] = None
    language: Optional[str] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    episode_count: Optional[int] = None


class RSSFeedResponse(BaseModel):
    success: bool
    message: str
    podcast_info: Optional[PodcastFeedInfo] = None


# States and Countries Models
class StateCountryData(BaseModel):
    id: int
    name: str
    country_id: int
    country_code: str
    country_name: str
    state_code: Optional[str] = None
    type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class StatesCountriesResponse(BaseModel):
    success: bool
    data: List[str]
    total: int


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


class UserStatusResponse(BaseModel):
    # User info
    user_id: Optional[str] = None
    email: Optional[str] = None

    # Sign-up confirmation status
    signup_confirmed: bool
    has_logged_in: bool

    # Onboarding status
    onboarding_completed: bool
    current_onboarding_step: int
    onboarding_steps_completed: Dict[str, bool]

    # Podcast claims status
    podcast_claim_sent: bool
    podcast_claim_verified: bool

    # Subscription status
    subscription_plan: str  # "free" or "pro"

    # Overall status
    overall_status: str  # "needs_confirmation", "needs_onboarding", "needs_podcast_verification", "complete"


# User Profile Models
class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None


class UserProfileResponse(BaseModel):
    id: str
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    avatar_url: Optional[str] = None
    podcast_id: Optional[str] = None
    podcast_name: Optional[str] = None
    connections_count: int = 0
    connection_status: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AvatarUploadResponse(BaseModel):
    success: bool
    avatar_url: Optional[str] = None


# User Interests Models
class TopicResponse(BaseModel):
    id: str
    name: str
    category: Optional[str] = None


class UserInterestResponse(BaseModel):
    id: str
    topic_id: str
    topic_name: str
    topic_category: Optional[str] = None
    created_at: str


class UpdateInterestsRequest(BaseModel):
    topic_ids: List[str]


class AddInterestRequest(BaseModel):
    topic_id: str


# User Connections Models
class ConnectionUserData(BaseModel):
    id: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    podcast_name: Optional[str] = None


class ConnectionResponse(BaseModel):
    connection_id: str
    user: ConnectionUserData
    status: str  # "pending", "accepted", "rejected"
    is_requester: bool
    created_at: str
    accepted_at: Optional[str] = None


class ConnectionRequestResponse(BaseModel):
    request_id: str
    requester: ConnectionUserData
    created_at: str


class ConnectionActionRequest(BaseModel):
    pass  # No body needed, user_id from path


class ConnectionsListResponse(BaseModel):
    connections: List[ConnectionResponse]
    total: int


class ConnectionStatusResponse(BaseModel):
    connected: bool
    status: Optional[str] = None
    connection_id: Optional[str] = None
    is_requester: Optional[bool] = None


# User Activity Models
class ActivityResponse(BaseModel):
    id: str
    activity_type: str
    activity_data: Dict[str, Any]
    user: ConnectionUserData
    created_at: str
    image_url: Optional[str] = None
    post: Optional[Dict[str, Any]] = None
    comment: Optional[Dict[str, Any]] = None
    podcast: Optional[Dict[str, Any]] = None
    episode: Optional[Dict[str, Any]] = None
    resource: Optional[Dict[str, Any]] = None


class ActivityFeedResponse(BaseModel):
    activities: List[ActivityResponse]
    total: int


class ActivityStatsResponse(BaseModel):
    period_days: int
    total_activities: int
    activity_breakdown: Dict[str, int]


# Message Media Models
class MessageMediaData(BaseModel):
    id: str
    message_id: str
    media_type: str  # 'image', 'video', 'audio', 'document'
    file_path: str
    filename: str
    file_size: int
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[int] = None
    thumbnail_path: Optional[str] = None
    display_order: int
    url: str  # Signed URL for accessing the media
    thumbnail_url: Optional[str] = None  # Signed URL for thumbnail
    created_at: str
    updated_at: str


class SendMessageWithMediaRequest(BaseModel):
    content: Optional[str] = None
    message_type: str = "text"
    reply_to_message_id: Optional[str] = None


class MessageMediaUploadResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    media: Optional[List[MessageMediaData]] = None


# Refresh Session Models
class RefreshSessionRequest(BaseModel):
    # No longer need refresh_token in body - will read from HttpOnly cookie
    pass


class RefreshSessionResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    error: Optional[str] = None
    refresh_token: Optional[str] = None  # New refresh token (rotation)


# Global Search Models
class GlobalSearchResponse(BaseModel):
    query: str
    offset: int
    limit: int
    total_results: int
    results: Dict[str, List[Dict[str, Any]]]
    cached: bool


class BlogCategory(BaseModel):
    id: str
    name: str


class ResourceCategoryResponse(BaseModel):
    name: str
    display_name: str
    description: str


# Stripe/Subscription Models
class CreateCheckoutSessionRequest(BaseModel):
    plan: Literal["pro_monthly", "lifetime"]


class CreateCheckoutSessionResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


class CreatePortalSessionRequest(BaseModel):
    return_url: Optional[str] = None


class CreatePortalSessionResponse(BaseModel):
    success: bool
    url: Optional[str] = None
    error: Optional[str] = None


class SubscriptionStatus(BaseModel):
    has_subscription: bool
    subscription_type: Optional[Literal["recurring", "lifetime"]] = None
    status: Optional[str] = (
        None  # active, canceled, past_due, lifetime_active, etc.
    )
    plan_id: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    trial_end: Optional[datetime] = None
    lifetime_access: Optional[bool] = None


class SubscriptionStatusResponse(BaseModel):
    success: bool
    subscription: Optional[SubscriptionStatus] = None
    error: Optional[str] = None


# Episode Listen Models
class RecordEpisodeListenResponse(BaseModel):
    success: bool
    is_first_listen: bool
    error: Optional[str] = None


class BlogCategory(BaseModel):
    id: str
    name: str


class BlogResponse(BaseModel):
    id: str
    slug: str
    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    author: str
    created_at: Optional[str] = None
    categories: List[BlogCategory] = []
    image_url: str


class BlogsResponse(BaseModel):
    blogs: List[BlogResponse]
    total_count: int
    has_more: bool
