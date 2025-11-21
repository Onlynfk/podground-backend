from pydantic import BaseModel, Field, validator, model_validator
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime
from enum import Enum


# Enums
class PostType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    POLL = "poll"


class ResourceType(str, Enum):
    ARTICLE = "article"
    VIDEO = "video"
    GUIDE = "guide"
    TOOL = "tool"
    TEMPLATE = "template"
    COURSE = "course"


class DifficultyLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


# Request Models
class CreatePostRequest(BaseModel):
    content: Optional[str] = Field(None, max_length=5000)
    post_type: PostType = PostType.TEXT
    media_urls: Optional[List[str]] = []
    podcast_episode_url: Optional[str] = None
    poll_options: Optional[List[str]] = None
    mentions: Optional[List[str]] = []  # List of user IDs
    hashtags: Optional[List[str]] = []

    @model_validator(mode="after")
    def validate_content_or_media(self):
        content = self.content
        media_urls = self.media_urls or []

        # Check if content exists and is not empty/whitespace
        has_content = content and content.strip()

        # Check if media exists
        has_media = media_urls and len(media_urls) > 0

        if not has_content and not has_media:
            raise ValueError(
                "Post must have either content or media attachments"
            )

        return self

    @validator("content")
    def validate_content_length(cls, v):
        # Convert empty strings to None for cleaner handling
        if v is not None and len(v.strip()) == 0:
            return None
        return v


class UpdatePostRequest(BaseModel):
    content: Optional[str] = Field(None, max_length=5000)
    media_urls: Optional[List[str]] = None
    mentions: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None


class CreateCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    parent_comment_id: Optional[str] = None  # For nested comments


class EditCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


class ConnectionActionRequest(BaseModel):
    user_id: str
    action: Literal["connect", "disconnect", "accept", "reject", "cancel"]


# Response Models
class UserProfileResponse(BaseModel):
    id: str
    name: str
    avatar_url: Optional[str] = None
    podcast_name: Optional[str] = None
    podcast_id: Optional[str] = None
    bio: Optional[str] = None


class MediaItemResponse(BaseModel):
    id: str
    url: str
    type: MediaType
    thumbnail_url: Optional[str] = None
    duration: Optional[int] = None  # For audio/video in seconds
    width: Optional[int] = None
    height: Optional[int] = None


class PostResponse(BaseModel):
    id: str
    user: UserProfileResponse
    content: Optional[str] = None
    post_type: PostType
    media_items: List[MediaItemResponse] = []
    podcast_episode_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Interaction counts
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    saves_count: int = 0

    # User interaction status
    is_liked: bool = False
    is_saved: bool = False
    is_shared: bool = False

    # Additional metadata
    mentions: List[UserProfileResponse] = []
    hashtags: List[str] = []
    poll_options: Optional[List[Dict[str, Any]]] = (
        None  # {option: str, votes: int, percentage: float, voted: bool}
    )

    # Post category (AI-assigned)
    category: Optional[Dict[str, str]] = (
        None  # {id, name, display_name, color, image_url}
    )


class CommentResponse(BaseModel):
    id: str
    post_id: str
    user: UserProfileResponse
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    parent_comment_id: Optional[str] = None
    replies_count: int = 0
    likes_count: int = 0
    is_liked: bool = False


class FeedResponse(BaseModel):
    posts: List[PostResponse]
    next_cursor: Optional[str] = None
    next_offset: Optional[int] = None
    has_more: bool = False
    total_returned: int = 0


class ConnectionResponse(BaseModel):
    id: str
    user: UserProfileResponse
    connected_at: Optional[datetime] = None
    status: str  # \"connected\", \"pending\", \"requested\"


# Resource Models
class CreateResourceRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    type: ResourceType
    url: Optional[str] = None
    image_url: Optional[str] = None
    author: Optional[str] = None
    read_time: Optional[int] = None  # minutes
    is_featured: bool = False
    category: str = Field(default="general", max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    video_url: Optional[str] = None
    download_url: Optional[str] = None
    duration: Optional[int] = None  # video duration in minutes
    difficulty_level: DifficultyLevel = DifficultyLevel.BEGINNER
    tags: Optional[List[str]] = []
    is_premium: bool = False
    thumbnail_url: Optional[str] = None


class ResourceResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    type: str
    url: Optional[str] = None
    image_url: Optional[str] = None
    author: Optional[str] = None
    read_time: Optional[int] = None
    is_featured: bool = False
    category: str
    video_url: Optional[str] = None
    download_url: Optional[str] = None
    tags: Optional[List[str]] = []
    is_premium: bool = False
    thumbnail_url: Optional[str] = None
    view_count: int = 0
    user_has_access: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Note: duration, difficulty_level, subcategory excluded from response
    status: str  # "connected", "pending", "requested"


class ConnectionListResponse(BaseModel):
    connections: List[ConnectionResponse]
    total_count: int
    next_cursor: Optional[str] = None
    has_more: bool = False


class SuggestedCreatorResponse(BaseModel):
    user: UserProfileResponse
    reason: Optional[str] = (
        None  # "Popular in your network", "Similar interests", etc.
    )
    mutual_connections: int = 0
    mutual_connection_names: List[str] = []


class TopicResponse(BaseModel):
    id: str
    name: str
    slug: str
    icon_url: Optional[str] = None
    description: Optional[str] = None
    follower_count: int = 0
    is_following: bool = False


class ResourceResponse(BaseModel):
    id: str
    title: str
    description: str
    type: str  # "article", "video", "guide", "tool"
    url: Optional[str] = None
    image_url: Optional[str] = None
    author: Optional[str] = None
    read_time: Optional[int] = None  # in minutes


class EventResponse(BaseModel):
    id: str
    title: str
    description: str
    start_date: datetime
    end_date: Optional[datetime] = None
    location: Optional[str] = None
    is_online: bool = False
    url: Optional[str] = None
    image_url: Optional[str] = None
    host: Optional[UserProfileResponse] = None
    attendee_count: int = 0
    is_attending: bool = False


class DiscoveryResponse(BaseModel):
    topics: List[TopicResponse] = []
    suggested_creators: List[SuggestedCreatorResponse] = []
    resources: List[ResourceResponse] = []
    upcoming_event: Optional[EventResponse] = None


# Add the missing response models that were referenced in main.py
class CommentsResponse(BaseModel):
    comments: List[CommentResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


class TopicsResponse(BaseModel):
    trending_topics: List[Dict[str, Any]]


class ResourcesResponse(BaseModel):
    resources: List[Dict[str, Any]]
    total_count: Optional[int] = None
    has_more: Optional[bool] = None


class EventsResponse(BaseModel):
    events: List[Dict[str, Any]]


# Subscription Models
class SubscriptionPlanData(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    price_monthly: float
    price_yearly: float
    features: List[str]
    can_access_premium_resources: bool = False
    can_access_analytics: bool = False
    can_create_events: bool = False
    is_active: bool = True


class UserSubscriptionData(BaseModel):
    plan: SubscriptionPlanData
    status: str
    starts_at: str
    ends_at: Optional[str] = None
    is_premium: bool = False


class SubscriptionPlansResponse(BaseModel):
    plans: List[SubscriptionPlanData]


class UserSubscriptionResponse(BaseModel):
    subscription: UserSubscriptionData


class CreateSubscriptionRequest(BaseModel):
    plan_name: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None


class UpdateSubscriptionRequest(BaseModel):
    status: str  # active, cancelled, expired


class UserRoleData(BaseModel):
    role: str
    granted_at: str
    expires_at: Optional[str] = None
    is_active: bool = True


class AssignRoleRequest(BaseModel):
    user_id: str
    role: str  # admin, podcaster


class AddReactionRequest(BaseModel):
    reaction_type: str = Field(..., min_length=1, max_length=50)

    @validator("reaction_type")
    def validate_reaction_type(cls, v):
        # Allow common emoji reactions and reaction names
        allowed_reactions = {
            "👍",
            "👎",
            "❤️",
            "😂",
            "😢",
            "😡",
            "😮",
            "🔥",
            "💯",
            "🎉",
            "like",
            "love",
            "laugh",
            "sad",
            "angry",
            "wow",
            "fire",
            "hundred",
            "party",
        }
        if v not in allowed_reactions:
            raise ValueError(
                f"Invalid reaction type. Allowed: {sorted(allowed_reactions)}"
            )
        return v


class ReactionResponse(BaseModel):
    id: str
    reaction_type: str
    user: UserProfileResponse
    created_at: datetime


class PostReactionsResponse(BaseModel):
    reactions: List[ReactionResponse]
    total_count: int
    user_reaction: Optional[str] = None  # Current user's reaction if any

