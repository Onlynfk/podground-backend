import os
import re
from uuid import UUID
from dotenv import load_dotenv

# Load environment variables FIRST before any other imports
load_dotenv()

# Debug: Print FRONTEND_URL to verify it's loaded
print(f"DEBUG: FRONTEND_URL from environment: {os.getenv('FRONTEND_URL')}")

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
    File,
    UploadFile,
    Query,
    Form,
)
from pydantic import Field
from typing import List, Dict, Any
import ipaddress
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    FileResponse,
    StreamingResponse,
    RedirectResponse,
    Response,
)
import django
from fastadmin import fastapi_app as admin_app
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
import jwt
from jwt.exceptions import InvalidTokenError
from datetime import datetime, timedelta, timezone
import requests
import logging
from disposable_email_domains import blocklist
from scheduler_service import scheduler_service


# Custom logging filter to suppress h11 LocalProtocolError (SSE client disconnects)
class SuppressH11ProtocolErrorFilter(logging.Filter):
    def filter(self, record):
        # Suppress h11 LocalProtocolError - this is normal when SSE clients disconnect
        if "LocalProtocolError" in str(
            record.msg
        ) or "Can't send data when our state is ERROR" in str(record.msg):
            return False
        # Also check exception info for LocalProtocolError
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type and "LocalProtocolError" in str(exc_type):
                return False
        return True


# Apply filter to both uvicorn error logger and root logger
logging.getLogger("uvicorn.error").addFilter(SuppressH11ProtocolErrorFilter())
logging.getLogger().addFilter(SuppressH11ProtocolErrorFilter())

from database import get_db, create_tables, init_ab_counter, ABCounter
from refresh_token_manager import RefreshTokenManager
from models import (
    WaitlistRequest,
    WaitlistResponse,
    MicrograntWaitlistRequest,
    MicrograntWaitlistResponse,
    ABVariantResponse,
    TokenResponse,
    SignUpRequest,
    SignInRequest,
    ResendMagicLinkRequest,
    CodeExchangeRequest,
    CodeExchangeResponse,
    AuthResponse,
    PodcastSearchResults,
    VerifyClaimByCodeRequest,
    ClaimResponse,
    OnboardingRequest,
    OnboardingResponse,
    CategoryResponse,
    NetworkResponse,
    OnboardingStatusResponse,
    OnboardingProfileResponse,
    PodcastClaimData,
    OnboardingStepRequest,
    PodcastCategoriesResponse,
    PodcastCategoryData,
    StateCountryData,
    StatesCountriesResponse,
    VerifyCodeRequest,
    UserStatusResponse,
    # Post models
    CreatePostRequest,
    UpdatePostRequest,
    CreateCommentRequest,
    EditCommentRequest,
    PostResponse,
    FeedResponse,
    CommentsResponse,
    ConnectionActionRequest,
    ConnectionListResponse,
    TopicsResponse,
    ResourcesResponse,
    EventsResponse,
    # Blog post models
    BlogResponse,
    BlogsResponse,
    # Subscription models
    SubscriptionPlansResponse,
    UserSubscriptionResponse,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    AssignRoleRequest,
    # User Profile models
    UpdateProfileRequest,
    UserProfileResponse,
    AvatarUploadResponse,
    TopicResponse,
    UserInterestResponse,
    UpdateInterestsRequest,
    AddInterestRequest,
    ConnectionUserData,
    ConnectionResponse,
    ConnectionRequestResponse,
    ConnectionsListResponse,
    ConnectionStatusResponse,
    ActivityResponse,
    ActivityFeedResponse,
    ActivityStatsResponse,
    # Message Media models
    MessageMediaData,
    SendMessageWithMediaRequest,
    MessageMediaUploadResponse,
    # Refresh Session models
    RefreshSessionRequest,
    RefreshSessionResponse,
    # Global Search models
    GlobalSearchResponse,
    # Stripe models
    CreateCheckoutSessionRequest,
    CreateCheckoutSessionResponse,
    CreatePortalSessionRequest,
    CreatePortalSessionResponse,
    SubscriptionStatus,
    SubscriptionStatusResponse,
    # Episode Listen models
    RecordEpisodeListenResponse,
    # Base model for new request classes
    BaseModel,
    BlogResponse,
    BlogsResponse,
    ResourceCategoryResponse,
)
from post_models import (
    CreateResourceRequest,
    ResourceResponse,
    AddReactionRequest,
    PostReactionsResponse,
    CreateGrantApplicationRequest,
    CreateGrantApplicationResponse
)
from customerio_client import CustomerIOClient
from supabase_client import SupabaseClient, get_supabase_client
from listennotes_client import ListenNotesClient
from podcast_endpoints import router as podcast_router
from post_endpoints import router as post_router
from jwt_utils import get_user_email_from_token
from security_utils import sanitize_for_log, sanitize_name, validate_search_query
from security_middleware import (
    SecurityHeadersMiddleware,
    RateLimitHeadersMiddleware,
    RequestValidationMiddleware,
)
from media_service import MediaService
from rss_parser import RSSFeedParser
from typing import Optional
from access_control import (
    init_access_control,
    get_access_control_dependency,
    require_role,
    require_subscription,
    require_premium_access,
)
from resources_service import resources_service
from events_service import events_service
from podcast_service import PodcastDiscoveryService
from user_listening_service import UserListeningService
from episode_listen_service import EpisodeListenService
from featured_content_service import FeaturedContentService
from messages_service import MessagesService
from resource_pdf_service import resource_pdf_service
from user_profile_service import UserProfileService
from user_interests_service import get_user_interests_service
from user_connections_service import get_user_connections_service
from user_activity_service import get_user_activity_service
from feed_cache_service import get_feed_cache_service
from user_settings_service import get_user_settings_service
from notification_service import NotificationService, notification_manager
from resource_interaction_service import get_resource_interaction_service
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")
django.setup()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress harmless h11 LocalProtocolError exceptions in asyncio
import asyncio
import sys


def suppress_h11_errors(loop, context):
    """Suppress h11 LocalProtocolError exceptions from asyncio"""
    exception = context.get("exception")
    if exception:
        exc_type = type(exception).__name__
        # Suppress h11 protocol errors (harmless keep-alive timeout errors)
        if exc_type == "LocalProtocolError" or "h11" in str(exception):
            return
    # Log other exceptions normally
    loop.default_exception_handler(context)


# Set the exception handler for asyncio (will be applied when event loop starts)
# We'll set this in the lifespan function to avoid deprecation warnings
_suppress_h11_errors = suppress_h11_errors

# Removed SessionCookieMiddleware - keeping it simple

# Enable debug logging for ListenNotes client temporarily
listennotes_logger = logging.getLogger("listennotes_client")
listennotes_logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
    init_ab_counter()
    # Set asyncio exception handler to suppress h11 errors
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_suppress_h11_errors)
    # Start the scheduler for background tasks
    await scheduler_service.start()
    yield
    # Shutdown
    await scheduler_service.stop()


limiter = Limiter(key_func=get_remote_address)

# Automatic favorite podcasts to add for all users
# These will be added automatically when users complete the favorite podcasts step
AUTOMATIC_FAVORITE_PODCASTS = [
    {
        "podcast_id": os.getenv("AUTO_FAVORITE_PODCAST_1_ID", ""),  # Set in environment
        "podcast_title": os.getenv("AUTO_FAVORITE_PODCAST_1_TITLE", ""),
        "podcast_image": os.getenv("AUTO_FAVORITE_PODCAST_1_IMAGE", ""),
        "podcast_publisher": os.getenv("AUTO_FAVORITE_PODCAST_1_PUBLISHER", ""),
    },
    {
        "podcast_id": os.getenv("AUTO_FAVORITE_PODCAST_2_ID", ""),  # Set in environment
        "podcast_title": os.getenv("AUTO_FAVORITE_PODCAST_2_TITLE", ""),
        "podcast_image": os.getenv("AUTO_FAVORITE_PODCAST_2_IMAGE", ""),
        "podcast_publisher": os.getenv("AUTO_FAVORITE_PODCAST_2_PUBLISHER", ""),
    },
]

# Maximum number of activity items to return per request
MAX_ACTIVITY_ITEMS = int(os.getenv("MAX_ACTIVITY_ITEMS", "10"))

app = FastAPI(title="PodGround Landing Page API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add exception handler for h11 LocalProtocolError (SSE client disconnects)
from h11._util import LocalProtocolError


async def h11_protocol_error_handler(request: Request, exc: LocalProtocolError):
    """
    Handle h11 LocalProtocolError that occurs when client disconnects from SSE stream.
    This is normal behavior and should not be logged as an error.
    """
    # Just return empty response - connection is already closed
    return Response(content="", status_code=200)


app.add_exception_handler(LocalProtocolError, h11_protocol_error_handler)

# Session middleware (add before other middleware)
session_secret = os.getenv("SESSION_SECRET_KEY", "your-secret-key-change-in-production")
session_hours = int(os.getenv("SESSION_MAX_AGE_HOURS", "24"))  # Default 24 hours
session_max_age = session_hours * 3600  # Convert to seconds
# Check environment - local, dev, or production
environment = os.getenv("ENVIRONMENT", "local").lower()
is_deployed = environment in ["dev", "production"]  # True for any deployed environment
is_production = environment == "production"  # True only for production

logger.info(
    f"Environment: {environment}, Is Deployed: {is_deployed}, Is Production: {is_production}"
)


# Custom middleware to handle session cookies with proper cross-origin settings
class SessionCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Check if there's a session cookie in the response
        if "set-cookie" in response.headers:
            origin = request.headers.get("origin")
            is_localhost_request = origin and (
                origin.startswith("http://localhost:3000")
                or origin.startswith("https://localhost:3000")
                or origin.startswith("http://localhost:3002")
                or origin.startswith("https://localhost:3002")
            )

            # Get environment info
            environment = os.getenv("ENVIRONMENT", "local").lower()
            is_deployed = environment in ["dev", "production"]

            # Determine proper cookie settings for cross-origin session cookies
            # The key insight: HTTP localhost origins can't use Secure cookies

            if origin and origin.startswith("http://localhost"):
                # HTTP localhost client: omit SameSite entirely for maximum compatibility
                cookie_secure = False  # Can't use Secure with HTTP origins
                cookie_samesite = None  # No SameSite attribute for cross-origin HTTP
                logger.info(
                    f"HTTP localhost detected: using permissive session cookies (no samesite)"
                )
            else:
                # HTTPS origins: use strict cross-origin settings
                cookie_secure = True
                cookie_samesite = "none"
                logger.info(f"HTTPS origin detected: using none session cookies")

            logger.info(
                f"Session cookie settings: origin={origin}, secure={cookie_secure}, samesite={cookie_samesite}"
            )

            # Modify session cookie if present
            cookies = response.headers.getlist("set-cookie")
            new_cookies = []

            for cookie in cookies:
                logger.debug(
                    f"Processing cookie: {cookie[:50]}..."
                )  # Log first 50 chars
                if cookie.startswith("session="):
                    # Log original cookie for debugging
                    logger.debug(f"Original session cookie: {cookie}")

                    # Parse and rebuild the session cookie with correct attributes
                    parts = cookie.split(";")
                    cookie_value = parts[0]  # session=value

                    # Build new cookie with proper attributes
                    new_cookie_parts = [cookie_value]

                    # Add attributes from original cookie but override security settings
                    for part in parts[1:]:
                        part = part.strip()
                        if part.lower().startswith(("secure", "samesite=", "domain=")):
                            continue  # Skip these, we'll add our own
                        new_cookie_parts.append(part)

                    # Add our security settings
                    if cookie_secure:
                        new_cookie_parts.append("Secure")
                    if cookie_samesite is not None:
                        new_cookie_parts.append(f"SameSite={cookie_samesite}")

                    new_cookie = "; ".join(new_cookie_parts)
                    new_cookies.append(new_cookie)

                    logger.debug(f"Final session cookie: {new_cookie}")
                    logger.info(
                        f"Modified session cookie: origin={origin}, is_localhost={is_localhost_request}, secure={cookie_secure}, samesite={cookie_samesite}"
                    )
                else:
                    new_cookies.append(cookie)

            # Update response headers
            if new_cookies:
                # Remove all existing set-cookie headers
                del response.headers["set-cookie"]
                # Add our modified cookies
                for cookie in new_cookies:
                    response.headers.append("set-cookie", cookie)

        return response


# Configure session middleware for cross-origin compatibility
# Configure session middleware with dynamic settings for cross-origin compatibility
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    max_age=session_max_age,
    same_site="lax",  # Default, will be overridden by custom middleware
    https_only=False,  # Default, will be overridden by custom middleware
)

# Enable custom session cookie middleware for cross-origin support
app.add_middleware(SessionCookieMiddleware)


# IP allowlist middleware for Swagger/docs endpoints
class DocsIPFilterMiddleware(BaseHTTPMiddleware):
    """Middleware to restrict access to API documentation endpoints by IP address"""

    def __init__(self, app, allowed_ips: list):
        super().__init__(app)
        self.allowed_ips = set(allowed_ips)
        self.docs_paths = {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        # Check if request is for docs/swagger endpoints
        if request.url.path in self.docs_paths:
            # Get client IP (handle proxies with X-Forwarded-For)
            client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if not client_ip:
                client_ip = request.headers.get("X-Real-IP", "").strip()
            if not client_ip:
                client_ip = request.client.host if request.client else "unknown"

            # Always log the IP attempting to access docs
            logger.info(
                f"Docs access attempt from IP: {client_ip} to {request.url.path}"
            )

            # Check if IP is in allowlist
            if self.allowed_ips and client_ip not in self.allowed_ips:
                logger.warning(
                    f"⛔ BLOCKED access to {request.url.path} from IP: {client_ip} (not in allowlist: {self.allowed_ips})"
                )
                return Response(
                    content="Access to API documentation is restricted", status_code=403
                )

            logger.info(f"✅ ALLOWED access to {request.url.path} from IP: {client_ip}")

        return await call_next(request)


# Get allowed IPs from environment variable
docs_allowed_ips_str = os.getenv("DOCS_ALLOWED_IPS", "")
if docs_allowed_ips_str:
    docs_allowed_ips = [
        ip.strip() for ip in docs_allowed_ips_str.split(",") if ip.strip()
    ]
    logger.info(f"Docs IP allowlist enabled: {docs_allowed_ips}")
    app.add_middleware(DocsIPFilterMiddleware, allowed_ips=docs_allowed_ips)
else:
    logger.warning("DOCS_ALLOWED_IPS not set - Swagger docs accessible from any IP")

# Security middleware (order matters - add security first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitHeadersMiddleware)
app.add_middleware(RequestValidationMiddleware)

# CORS configuration for Next.js frontend
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
# Strip any whitespace from origins
allowed_origins = [origin.strip() for origin in allowed_origins]
# Always allow localhost for development testing (both HTTP and HTTPS)
if "http://localhost:3000" not in allowed_origins:
    allowed_origins.append("http://localhost:3000")
if "https://localhost:3000" not in allowed_origins:
    allowed_origins.append("https://localhost:3000")
# Add support for test client on port 3001
if "http://localhost:3001" not in allowed_origins:
    allowed_origins.append("http://localhost:3001")
if "https://localhost:3001" not in allowed_origins:
    allowed_origins.append("https://localhost:3001")
# Add support for test client on port 3002
if "http://localhost:3002" not in allowed_origins:
    allowed_origins.append("http://localhost:3002")
if "https://localhost:3002" not in allowed_origins:
    allowed_origins.append("https://localhost:3002")

# Allow null origin for local file:// testing (development only)
# WARNING: Remove this in production!
environment = os.getenv("ENVIRONMENT", "dev")
if environment in ["dev", "development"]:
    if "null" not in allowed_origins:
        allowed_origins.append("null")
        logger.warning("CORS: Allowing 'null' origin for local file:// testing (development only)")

# Allow Netlify deployments (for testing)
# Note: We'll allow all Netlify domains since they change with each deployment
# In production, you should specify exact domains
netlify_domains = [
    "https://pgclientapp.netlify.app",
    # Add the specific deployment URL that's currently failing
    "https://68dadaeb67d2ea9b545c3ad7--pgclientapp.netlify.app",
]
for domain in netlify_domains:
    if domain not in allowed_origins:
        allowed_origins.append(domain)

logger.info(f"Configured CORS allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize clients
customerio_client = CustomerIOClient()
supabase_client = SupabaseClient()
listennotes_client = ListenNotesClient()
rss_parser = RSSFeedParser()

# Initialize Listen system services
podcast_service = PodcastDiscoveryService(supabase_client.service_client)
user_listening_service = UserListeningService(supabase_client.service_client)
featured_content_service = FeaturedContentService(supabase_client.service_client)

# Initialize Messages system services
messages_service = MessagesService(supabase_client)

# Initialize access control
init_access_control(supabase_client)

# Include routers
app.include_router(podcast_router, prefix="/api/v1/podcasts", tags=["Podcasts"])
app.include_router(post_router, prefix="/api/v1/posts", tags=["Posts"])


def split_name(full_name: str) -> tuple[str, str]:
    """
    Split a full name into first and last name.
    If only one name is provided, store it as first name.
    """
    if not full_name or not full_name.strip():
        return "", ""

    # Clean and split the name
    name_parts = full_name.strip().split()

    if len(name_parts) == 1:
        # Only one name provided - store as first name
        return name_parts[0], ""
    elif len(name_parts) == 2:
        # Two names - first and last
        return name_parts[0], name_parts[1]
    else:
        # More than two names - first name is first part, last name is everything else
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])
        return first_name, last_name


def is_disposable_email(email: str) -> bool:
    """Check if email domain is a known disposable email provider"""
    domain = email.split("@")[1].lower()
    return domain in blocklist


def is_rss_url(input_string: str) -> bool:
    """Detect if input string is an RSS URL"""
    input_string = input_string.strip().lower()

    # Check if it starts with http/https
    if not (input_string.startswith("http://") or input_string.startswith("https://")):
        return False

    # Common RSS URL patterns
    rss_indicators = [
        "rss",
        "feed",
        "podcast",
        "xml",
        "atom",
        "feeds/",
        "/rss",
        "/feed",
        "/podcast",
        "itunes",
        "apple",
        "spotify",
    ]

    # Check if URL contains RSS-related keywords
    for indicator in rss_indicators:
        if indicator in input_string:
            return True

    # Check for common RSS file extensions
    if input_string.endswith((".xml", ".rss", ".atom")):
        return True

    return False


def get_magic_link_expiry_seconds() -> int:
    """Get magic link expiry time in seconds from environment variable"""
    hours = int(os.getenv("MAGIC_LINK_EXPIRY_HOURS", "24"))
    return hours * 3600  # Convert hours to seconds


def get_verification_code_expiry_hours() -> int:
    """Get verification code expiry time in hours from environment variable"""
    return int(os.getenv("VERIFICATION_CODE_EXPIRY_HOURS", "24"))


def require_localhost(request: Request) -> None:
    """Dependency to ensure request is coming from localhost"""
    client_host = request.client.host

    # List of allowed localhost addresses
    localhost_addresses = [
        "127.0.0.1",
        "localhost",
        "::1",  # IPv6 localhost
        "0.0.0.0",
    ]

    # Check if client is localhost
    is_localhost = False

    # Direct match
    if client_host in localhost_addresses:
        is_localhost = True

    # Check if it's a loopback address
    try:
        addr = ipaddress.ip_address(client_host)
        if addr.is_loopback:
            is_localhost = True
    except ValueError:
        # Not a valid IP address, might be a hostname
        if client_host.lower() in ["localhost", "host.docker.internal"]:
            is_localhost = True

    # Also check X-Forwarded-For header in case of proxy
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # Get the first IP in the chain (original client)
        first_ip = x_forwarded_for.split(",")[0].strip()
        if first_ip in localhost_addresses:
            is_localhost = True
        try:
            addr = ipaddress.ip_address(first_ip)
            if addr.is_loopback:
                is_localhost = True
        except ValueError:
            pass

    if not is_localhost:
        logger.warning(
            f"Attempted admin access from non-localhost address: {client_host}"
        )
        raise HTTPException(
            status_code=403, detail="Admin endpoints are only accessible from localhost"
        )


def get_current_user_from_session(request: Request) -> str:
    """Get current user ID from session cookie or Bearer token"""
    # First try session cookie
    user_id = request.session.get("user_id")
    session_keys = list(request.session.keys()) if request.session else []
    logger.info(f"Session check - user_id: {user_id}, session_keys: {session_keys}")

    # If no session, check for Bearer token
    if not user_id:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix

            # Check if token exists in app state
            if (
                hasattr(app.state, "session_tokens")
                and token in app.state.session_tokens
            ):
                token_data = app.state.session_tokens[token]

                # Check if token is still valid
                if token_data["expires"] > datetime.utcnow():
                    logger.info(
                        f"Valid Bearer token found for user {token_data['user_id']}"
                    )
                    return token_data["user_id"]
                else:
                    # Clean up expired token
                    del app.state.session_tokens[token]
                    logger.warning("Bearer token expired")
            else:
                logger.warning(f"Bearer token not found or invalid")

    if not user_id:
        logger.warning(
            f"No user_id in session or valid token. Available session keys: {session_keys}"
        )
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def get_current_user_from_session_optional(request: Request) -> Optional[str]:
    """Get current user ID from session cookie, return None if not authenticated"""
    user_id = request.session.get("user_id")
    return user_id  # Return None if not found, don't raise exception


# Alias for consistency with existing code
get_current_user_id = get_current_user_from_session


def check_user_has_verified_podcast_claim(user_id: str) -> bool:
    """Check if user has at least one verified podcast claim"""
    try:
        claims_result = supabase_client.get_user_podcast_claims_session(user_id)
        if claims_result["success"] and claims_result["data"]:
            # Check if any claim is verified
            for claim in claims_result["data"]:
                if claim.get("is_verified", False):
                    return True
        return False
    except Exception as e:
        logger.error(f"Error checking podcast claims for user {user_id}: {str(e)}")
        return False


def get_user_display_name(user_id: str, fallback_email: str = "") -> str:
    """Get user's display name from Supabase, with email fallback"""
    try:
        if user_id and supabase_client.service_client:
            user_data = supabase_client.service_client.auth.admin.get_user_by_id(
                user_id
            )
            if (
                user_data
                and hasattr(user_data, "user")
                and user_data.user.user_metadata
            ):
                first_name = user_data.user.user_metadata.get("first_name", "")
                last_name = user_data.user.user_metadata.get("last_name", "")
                user_name = f"{first_name} {last_name}".strip()
                if user_name:
                    return user_name
            # Try to get email from user data if not provided
            if (
                not fallback_email
                and hasattr(user_data, "user")
                and user_data.user.email
            ):
                fallback_email = user_data.user.email
    except Exception as e:
        logger.warning(f"Could not get user display name: {str(e)}")

    # Fallback to email prefix
    return fallback_email.split("@")[0] if fallback_email else "User"


def verify_captcha(token: str) -> bool:
    """Verify captcha token with Google reCAPTCHA with enhanced validation"""
    secret_key = os.getenv("CAPTCHA_SECRET_KEY")
    if not secret_key:
        return False

    # Don't allow test tokens in production
    if secret_key != "test_secret" and token in ["test_token", "test", ""]:
        return False

    url = "https://www.google.com/recaptcha/api/siteverify"
    payload = {"secret": secret_key, "response": token}

    try:
        response = requests.post(url, data=payload, timeout=10)
        result = response.json()

        # Enhanced validation
        success = result.get("success", False)
        score = result.get("score", 0)
        action = result.get("action", "")

        # For test environment, allow test tokens
        if secret_key == "test_secret" and token == "test_token":
            return True

        # For production, check score and action
        if success and score >= 0.5:
            return True

        return False
    except Exception as e:
        return False


@app.get("/api/v1/ab-variant", response_model=ABVariantResponse, tags=["A/B Testing"])
async def get_ab_variant(db: Session = Depends(get_db)):
    """Get A/B variant using round-robin logic"""
    counter = db.query(ABCounter).first()

    # Increment counter
    counter.count += 1
    db.commit()

    # Return variant based on odd/even
    variant = "A" if counter.count % 2 == 1 else "B"

    return ABVariantResponse(variant=variant)


# Referer validation removed - easily spoofable and not reliable for security


def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=15
        )  # Default 15 minutes

    to_encode.update({"exp": expire})
    secret_key = os.getenv("JWT_SECRET_KEY")
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm="HS256")
    return encoded_jwt


def verify_token(token: str):
    """Verify JWT token"""
    try:
        secret_key = os.getenv("JWT_SECRET_KEY")
        # PyJWT automatically validates expiry when decoding
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except InvalidTokenError:
        return None
    except Exception:
        return None


@app.get("/api/v1/token", response_model=TokenResponse, tags=["Waitlist"])
@limiter.limit("10/minute")
async def get_token(request: Request):
    """Get JWT token for waitlist submission"""

    # Token generation - no additional validation needed beyond CORS

    # Create token with short expiry (5 minutes)
    token_data = {
        "purpose": "waitlist_submission",
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    access_token = create_access_token(token_data, timedelta(minutes=5))

    return TokenResponse(token=access_token, expires_in=300)  # 5 minutes


@app.post("/api/v1/waitlist", response_model=WaitlistResponse, tags=["Waitlist"])
@limiter.limit("5/minute")
async def submit_waitlist(
    waitlist_data: WaitlistRequest, request: Request, db: Session = Depends(get_db)
):
    """Submit email to waitlist via Customer.io with JWT protection"""

    # 1. Input Validation
    if (
        not waitlist_data.name
        or not waitlist_data.email
        or not waitlist_data.variant
        or not waitlist_data.captcha_token
    ):
        raise HTTPException(
            status_code=400,
            detail="Name, email, variant and captcha token are required",
        )

    # Validate variant
    if waitlist_data.variant not in ["A", "B"]:
        raise HTTPException(status_code=400, detail="Variant must be 'A' or 'B'")

    # Check for disposable email
    if is_disposable_email(waitlist_data.email):
        raise HTTPException(
            status_code=400, detail="Disposable email addresses are not allowed"
        )

    # 2. JWT Token Validation
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ")[1]
    payload = verify_token(token)
    if not payload or payload.get("purpose") != "waitlist_submission":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not verify_captcha(waitlist_data.captcha_token):
        raise HTTPException(status_code=400, detail="Invalid captcha verification")

    # Validate and sanitize name
    try:
        sanitized_name = sanitize_name(waitlist_data.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Split the name into first and last name
    first_name, last_name = split_name(sanitized_name)

    # 1. Save to Supabase first (ALWAYS succeeds - graceful degradation)
    try:
        supabase_result = supabase_client.add_waitlist_email(
            email=waitlist_data.email,
            first_name=first_name,
            last_name=last_name,
            variant=waitlist_data.variant,
        )

        if not supabase_result["success"]:
            error_msg = supabase_result.get("error", "Failed to save email")
            if "already exists" in error_msg.lower():
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "message": "Email already exists in waitlist",
                    },
                )
            else:
                raise HTTPException(
                    status_code=500, detail=f"Database error: {error_msg}"
                )

        waitlist_record = supabase_result["data"]
        record_id = waitlist_record["id"]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Supabase waitlist save failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal server error: Failed to save email"
        )

    # 2. Try to sync to Customer.io (best effort - non-blocking)
    try:
        customerio_result = customerio_client.add_contact(
            waitlist_data.email, first_name, last_name, waitlist_data.variant
        )

        if customerio_result["success"]:
            # Mark as synced in Supabase
            supabase_client.update_customerio_sync_status(
                "waitlist_emails", record_id, "synced"
            )
            logger.info(f"Successfully synced {waitlist_data.email} to Customer.io")
            sync_message = " and Customer.io"
        else:
            # Mark as failed but don't fail the entire request
            supabase_client.update_customerio_sync_status(
                "waitlist_emails", record_id, "failed", increment_attempts=True
            )
            error_msg = customerio_result.get("error", "Unknown Customer.io error")
            logger.warning(
                f"Customer.io sync failed for {waitlist_data.email}: {sanitize_for_log(error_msg)}"
            )
            sync_message = " (Customer.io sync will be retried later)"

    except Exception as e:
        # Customer.io exception - mark as failed but don't fail the request
        supabase_client.update_customerio_sync_status(
            "waitlist_emails", record_id, "failed", increment_attempts=True
        )
        logger.warning(
            f"Customer.io sync exception for {waitlist_data.email}: {sanitize_for_log(str(e))}"
        )
        sync_message = " (Customer.io sync will be retried later)"

    # 3. ALWAYS return success to user (data is safe in Supabase)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"Successfully added to waitlist{sync_message}",
        },
    )


@app.post(
    "/api/v1/microgrant-waitlist",
    response_model=MicrograntWaitlistResponse,
    tags=["Waitlist"],
)
@limiter.limit("5/minute")
async def submit_microgrant_waitlist(
    waitlist_data: MicrograntWaitlistRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit email to microgrant waitlist via Customer.io with JWT protection and graceful degradation"""

    # 1. Input Validation
    if (
        not waitlist_data.name
        or not waitlist_data.email
        or not waitlist_data.captcha_token
    ):
        raise HTTPException(
            status_code=400, detail="Name, email and captcha token are required"
        )

    # Check for disposable email
    if is_disposable_email(waitlist_data.email):
        raise HTTPException(
            status_code=400, detail="Disposable email addresses are not allowed"
        )

    # 2. JWT Token Validation
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ")[1]
    payload = verify_token(token)
    if not payload or payload.get("purpose") != "waitlist_submission":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not verify_captcha(waitlist_data.captcha_token):
        raise HTTPException(status_code=400, detail="Invalid captcha verification")

    # Validate and sanitize name
    try:
        sanitized_name = sanitize_name(waitlist_data.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Split the name into first and last name
    first_name, last_name = split_name(sanitized_name)

    # 1. Save to Supabase first (ALWAYS succeeds - graceful degradation)
    try:
        supabase_result = supabase_client.add_microgrant_waitlist_email(
            email=waitlist_data.email, first_name=first_name, last_name=last_name
        )

        if not supabase_result["success"]:
            error_msg = supabase_result.get("error", "Failed to save email")
            if "already exists" in error_msg.lower():
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "message": "Email already exists in microgrant waitlist",
                    },
                )
            else:
                raise HTTPException(
                    status_code=500, detail=f"Database error: {error_msg}"
                )

        waitlist_record = supabase_result["data"]
        record_id = waitlist_record["id"]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Supabase microgrant waitlist save failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal server error: Failed to save email"
        )

    # 2. Try to sync to Customer.io (best effort - non-blocking)
    try:
        customerio_result = customerio_client.add_microgrant_contact(
            waitlist_data.email, first_name, last_name
        )

        if customerio_result["success"]:
            # Mark as synced in Supabase
            supabase_client.update_customerio_sync_status(
                "microgrant_waitlist_emails", record_id, "synced"
            )
            logger.info(f"Successfully synced {waitlist_data.email} to Customer.io")
            sync_message = " and Customer.io"
        else:
            # Mark as failed but don't fail the entire request
            supabase_client.update_customerio_sync_status(
                "microgrant_waitlist_emails",
                record_id,
                "failed",
                increment_attempts=True,
            )
            error_msg = customerio_result.get("error", "Unknown Customer.io error")
            logger.warning(
                f"Customer.io sync failed for {waitlist_data.email}: {sanitize_for_log(error_msg)}"
            )
            sync_message = " (Customer.io sync will be retried later)"

    except Exception as e:
        # Customer.io exception - mark as failed but don't fail the request
        supabase_client.update_customerio_sync_status(
            "microgrant_waitlist_emails", record_id, "failed", increment_attempts=True
        )
        logger.warning(
            f"Customer.io sync exception for {waitlist_data.email}: {sanitize_for_log(str(e))}"
        )
        sync_message = " (Customer.io sync will be retried later)"

    # 3. ALWAYS return success to user (data is safe in Supabase)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"Successfully added to microgrant waitlist{sync_message}",
        },
    )


# Authentication Endpoints (Magic Link)
@app.post("/api/v1/auth/signup", response_model=AuthResponse, tags=["Authentication"])
@limiter.limit("5/minute")
async def signup(signup_data: SignUpRequest, request: Request):
    """Sign up user with magic link"""

    # Input validation
    if not signup_data.name or not signup_data.email:
        raise HTTPException(status_code=400, detail="Name and email are required")

    # Validate and sanitize name
    try:
        sanitized_name = sanitize_name(signup_data.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check for disposable email
    if is_disposable_email(signup_data.email):
        raise HTTPException(
            status_code=400, detail="Disposable email addresses are not allowed"
        )

    try:
        # Redirect to frontend callback page (admin.generate_link doesn't support PKCE)
        # Frontend will extract token from hash and call backend
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        redirect_url = f"{frontend_url}/auth/callback"
        
        # Step 1: Create user in Supabase without sending email
        result = supabase_client.create_user_without_email(
            signup_data.email, sanitized_name
        )

        if result["success"]:
            user_data = result.get("data")
            user_id = None
            if user_data and hasattr(user_data, "user"):
                user_id = user_data.user.id

            # Step 2: Generate magic link for Customer.io email
            magic_link_result = supabase_client.generate_magic_link(
                signup_data.email,
                redirect_url,
                expiry_seconds=get_magic_link_expiry_seconds(),
            )

            magic_link_url = ""
            long_token = ""
            if magic_link_result["success"]:
                magic_link_data = magic_link_result.get("data")
                if magic_link_data and hasattr(magic_link_data, "properties"):
                    magic_link_url = magic_link_data.properties.action_link
                    long_token = magic_link_data.properties.hashed_token
            else:
                logger.warning(
                    f"Failed to generate magic link: {magic_link_result.get('error')}"
                )

            # Generate a short numeric verification code
            short_code = supabase_client.generate_short_verification_code(
                user_id, length=6
            )

            # Step 3: Send signup confirmation via Customer.io transactional email
            logger.info(
                f"DEBUG: About to send Customer.io email with: email={signup_data.email}, name={sanitized_name}, magic_link_url={magic_link_url}, verification_code={short_code}"
            )
            customerio_result = (
                customerio_client.send_signup_confirmation_transactional(
                    email=signup_data.email,
                    name=sanitized_name,
                    magic_link_url=magic_link_url,
                    verification_code=short_code,
                )
            )

            if not customerio_result["success"]:
                logger.warning(
                    f"Customer.io signup confirmation failed: {customerio_result.get('error')}"
                )
                # Don't fail the signup if Customer.io fails
                # For debugging: print the verification code to logs
                logger.info(
                    f"DEBUG: Verification code for {signup_data.email}: {short_code}"
                )
                logger.info(f"DEBUG: Magic link: {magic_link_url}")

            # Step 4: Track user signup for first-time login reminder in Supabase
            if user_id:
                try:
                    # First check if tracking record already exists
                    existing_tracking = supabase_client.get_signup_tracking_by_user_id(
                        user_id
                    )

                    if not existing_tracking["success"] or not existing_tracking.get(
                        "data"
                    ):
                        # No existing tracking record, create one
                        tracking_result = supabase_client.create_signup_tracking(
                            user_id=user_id,
                            email=signup_data.email,
                            name=sanitized_name,
                        )
                        if tracking_result["success"]:
                            logger.info(
                                f"Created signup tracking record for user {user_id}"
                            )
                        else:
                            logger.error(
                                f"Failed to create signup tracking: {tracking_result.get('error')}"
                            )
                    else:
                        logger.info(
                            f"Signup tracking already exists for user {user_id}"
                        )
                except Exception as e:
                    logger.error(f"Failed to create signup tracking record: {str(e)}")
                    # Don't fail the signup if tracking fails
                    pass

            return AuthResponse(
                success=True,
                message=f"We just sent a confirmation email to {signup_data.email}",
                user_id=user_id,
            )
        else:
            error_msg = result.get("error", "Unknown signup error")
            if "already registered" in error_msg.lower():
                raise HTTPException(status_code=409, detail="Email already registered")
            else:
                raise HTTPException(
                    status_code=500, detail=f"Signup failed: {error_msg}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/auth/verify-code",
    response_model=CodeExchangeResponse,
    tags=["Authentication"],
)
@limiter.limit("10/minute")
async def verify_code_for_session(
    verify_data: VerifyCodeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a 6-digit code and create server session (alternative to magic link)"""

    if not verify_data.email or not verify_data.code:
        raise HTTPException(status_code=400, detail="Email and code are required")

    # Validate code format (6 digits)
    if not verify_data.code.isdigit() or len(verify_data.code) != 6:
        raise HTTPException(status_code=400, detail="Code must be 6 digits")

    try:
        logger.info(f"Verifying 6-digit code for email: {verify_data.email}")

        # Verify the code with Supabase
        result = supabase_client.verify_short_code(verify_data.email, verify_data.code)

        if not result["success"]:
            error_msg = result.get("error", "Code verification failed")
            if "not found" in error_msg.lower():
                raise HTTPException(status_code=404, detail="User not found")
            elif "invalid" in error_msg.lower():
                raise HTTPException(
                    status_code=400, detail="Invalid or expired verification code"
                )
            else:
                raise HTTPException(status_code=500, detail=f"Verification failed: {error_msg}")

        user_id = result.get("user_id")
        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to get user ID from verification")

        user_email = verify_data.email
        logger.info(f"Code verification successful for user {user_id}")

        # Create server session (same as magic link flow)
        request.session["user_id"] = user_id
        request.session["user_email"] = user_email
        request.session["authenticated"] = True

        # Force session to save
        logger.info(f"Session data set: user_id={user_id}, email={user_email}")

        # Create signup tracking record if it doesn't exist
        logger.info(f"Starting signup tracking for user {user_id}")
        try:
            # First check if tracking record already exists
            existing_tracking = supabase_client.get_signup_tracking_by_user_id(user_id)

            if not existing_tracking["success"] or not existing_tracking.get("data"):
                # No existing tracking record, create one
                user_name = get_user_display_name(user_id, user_email)

                tracking_result = supabase_client.create_signup_tracking(
                    user_id=user_id, email=user_email, name=user_name
                )

                if tracking_result["success"]:
                    logger.info(
                        f"Created signup tracking record for code-verified user {user_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to create signup tracking: {tracking_result.get('error')}"
                    )
            else:
                logger.info(f"Signup tracking already exists for user {user_id}")

            # Mark signup as confirmed
            confirmation_result = supabase_client.mark_signup_confirmed(user_id)
            if confirmation_result["success"]:
                logger.info(f"Marked signup confirmed via 6-digit code for user {user_id}")

                # Add signup_confirmed attribute to Customer.io
                try:
                    customerio_result = customerio_client.update_user_attributes(
                        user_id=user_id,
                        email=user_email,
                        attributes={"signup_confirmed": True}
                    )
                    if customerio_result["success"]:
                        logger.info(f"Customer.io: Added signup_confirmed attribute for {user_email}")
                    else:
                        logger.warning(f"Customer.io: Failed to add signup_confirmed: {customerio_result.get('error')}")
                except Exception as e:
                    logger.warning(f"Customer.io signup_confirmed tracking error (non-fatal): {str(e)}")
            else:
                logger.warning(
                    f"Failed to mark signup confirmed: {confirmation_result.get('error')}"
                )
        except Exception as e:
            logger.warning(f"Signup confirmation error (non-fatal): {str(e)}", exc_info=True)

        # Mark first login
        try:
            login_result = supabase_client.mark_first_login(user_id)
            if login_result["success"]:
                logger.info(f"Marked first login for user {user_id}")
        except Exception as e:
            logger.warning(
                f"First login marking error (non-fatal): {str(e)}", exc_info=True
            )

        # Invalidate episode cache for user's favorite podcasts on sign-in
        try:
            favorite_podcasts = await podcast_service.get_user_favorite_podcasts(user_id)
            if favorite_podcasts:
                invalidated_count = 0
                for podcast in favorite_podcasts:
                    podcast_id = podcast.get('id')
                    if podcast_id:
                        podcast_service.episode_cache.invalidate_podcast(podcast_id)
                        invalidated_count += 1
                logger.info(f"Invalidated episode cache for {invalidated_count} favorite podcasts on user sign-in: {user_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate episode cache on sign-in (non-fatal): {str(e)}", exc_info=True)

        # Invalidate user profile cache on sign-in to fetch fresh data
        try:
            from user_profile_cache_service import get_user_profile_cache_service
            profile_cache = get_user_profile_cache_service()
            profile_cache.invalidate(user_id)
            logger.info(f"Invalidated user profile cache on sign-in: {user_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate profile cache on sign-in (non-fatal): {str(e)}", exc_info=True)

        # Create 90-day refresh token for persistent login
        try:
            user_agent = request.headers.get("User-Agent")
            ip_address = request.client.host if request.client else None

            refresh_token = RefreshTokenManager.create_refresh_token(
                db=db,
                user_id=user_id,
                user_agent=user_agent,
                ip_address=ip_address,
                days_valid=90,
            )

            # Set refresh token as HttpOnly cookie
            refresh_token_max_age = 90 * 24 * 60 * 60  # 90 days in seconds
            origin = request.headers.get("origin")
            is_localhost_request = origin and (
                "localhost" in origin or "127.0.0.1" in origin
            )

            # Configure cookie security based on environment
            if is_localhost_request:
                cookie_secure = False  # Allow HTTP for localhost
                cookie_samesite = "lax"
            else:
                cookie_secure = True  # Always secure for production
                cookie_samesite = "none"  # Required for cross-origin

            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=refresh_token_max_age,
                httponly=True,
                secure=cookie_secure,
                samesite=cookie_samesite,
                domain=None,
            )

            logger.info(
                f"Created refresh token for user {user_id} (secure={cookie_secure}, samesite={cookie_samesite})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to create refresh token (non-fatal): {str(e)}", exc_info=True
            )

        logger.info(f"About to return success response for user {user_id}")

        # For cross-origin requests where cookies don't work, create a one-time session token
        session_token = None
        origin = request.headers.get("origin", "")
        logger.info(f"Origin header: '{origin}', checking for localhost")

        # Check if this is a cross-origin request that needs special handling
        if origin and "localhost" in origin:
            import secrets
            from datetime import datetime, timedelta

            # Generate a secure one-time token
            session_token = secrets.token_urlsafe(32)

            # Store token temporarily in app state (in production, use Redis or similar)
            if not hasattr(app.state, "session_tokens"):
                app.state.session_tokens = {}

            # Clean up expired tokens
            now = datetime.utcnow()
            app.state.session_tokens = {
                k: v for k, v in app.state.session_tokens.items() if v["expires"] > now
            }

            # Store new token
            app.state.session_tokens[session_token] = {
                "user_id": user_id,
                "user_email": user_email,
                "expires": now + timedelta(minutes=5),
            }

            logger.info(
                f"Created one-time session token for cross-origin auth: {session_token[:10]}..."
            )

        # Return session-only authentication response
        response_data = CodeExchangeResponse(
            ok=True,
            message="Code verified successfully! You are now logged in.",
            access_token=session_token,  # Include token for cross-origin clients
        )

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code verification error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/v1/auth/signin", response_model=AuthResponse, tags=["Authentication"])
@limiter.limit("5/minute")
async def signin(signin_data: SignInRequest, request: Request):
    """Sign in user with magic link"""

    if not signin_data.email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        # Get user by email first
        user_result = supabase_client.get_user_id_by_email(signin_data.email)
        if not user_result["success"]:
            raise HTTPException(status_code=404, detail="User not found")

        user = user_result["user"]

        # Get user's display name
        user_name = ""
        if hasattr(user, "user_metadata") and user.user_metadata:
            first_name = user.user_metadata.get("first_name", "")
            last_name = user.user_metadata.get("last_name", "")
            user_name = f"{first_name} {last_name}".strip()
        
        if not user_name and hasattr(user, 'email'):
            user_name = user.email.split('@')[0]  # Fallback to email username
        
        # Get URLs for redirect - use frontend callback (admin.generate_link doesn't support PKCE)
        # Frontend will extract token from hash and call backend
        frontend_url = os.getenv("FRONTEND_URL")
        redirect_url = f"{frontend_url}/auth/callback"

        # Generate magic link
        magic_link_result = supabase_client.generate_magic_link(
            signin_data.email,
            redirect_url,
            expiry_seconds=get_magic_link_expiry_seconds(),
        )

        magic_link_url = ""
        if magic_link_result["success"]:
            magic_link_data = magic_link_result.get("data")
            if magic_link_data and hasattr(magic_link_data, "properties"):
                magic_link_url = magic_link_data.properties.action_link
        else:
            logger.warning(
                f"Failed to generate magic link: {magic_link_result.get('error')}"
            )
            raise HTTPException(status_code=500, detail="Failed to generate magic link")

        # Generate verification code for signin
        user_id = user_result["user_id"]
        short_code = supabase_client.generate_short_verification_code(user_id, length=6)

        # Send signin email (magic link + verification code)
        customerio_result = customerio_client.send_signin_transactional(
            email=signin_data.email,
            name=user_name,
            magic_link_url=magic_link_url,
            verification_code=short_code,
        )

        if not customerio_result["success"]:
            logger.error(
                f"Customer.io signin email failed: {customerio_result.get('error')}"
            )
            raise HTTPException(status_code=500, detail="Failed to send login email")

        return AuthResponse(
            success=True,
            message=f"We just sent a login url and verification code to {signin_data.email}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signin error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/v1/auth/resend", response_model=AuthResponse, tags=["Authentication"])
@limiter.limit("3/minute")
async def resend_auth_credentials(
    resend_data: ResendMagicLinkRequest, request: Request
):
    """Resend magic link and verification code for authentication"""

    if not resend_data.email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        # Get user by email to obtain user_id
        user_result = supabase_client.get_user_id_by_email(resend_data.email)
        if not user_result["success"]:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_result["user_id"]
        user = user_result["user"]

        # Get user's display name
        user_name = ""
        if hasattr(user, "user_metadata") and user.user_metadata:
            first_name = user.user_metadata.get("first_name", "")
            last_name = user.user_metadata.get("last_name", "")
            user_name = f"{first_name} {last_name}".strip()
        
        if not user_name and hasattr(user, 'email'):
            user_name = user.email.split('@')[0]  # Fallback to email username
        
        # Get URLs for redirect - use frontend callback (admin.generate_link doesn't support PKCE)
        # Frontend will extract token from hash and call backend
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        redirect_url = f"{frontend_url}/auth/callback"

        # Generate new magic link (this invalidates the previous one by creating a new one)
        magic_link_result = supabase_client.generate_magic_link(
            resend_data.email,
            redirect_url,
            expiry_seconds=get_magic_link_expiry_seconds(),
        )

        magic_link_url = ""
        if magic_link_result["success"]:
            magic_link_data = magic_link_result.get("data")
            if magic_link_data and hasattr(magic_link_data, "properties"):
                magic_link_url = magic_link_data.properties.action_link
        else:
            logger.warning(
                f"Failed to generate magic link: {magic_link_result.get('error')}"
            )
            raise HTTPException(status_code=500, detail="Failed to generate magic link")

        # Check if user has already confirmed their signup
        signup_status = supabase_client.check_user_signup_confirmed(user_id)

        # Generate verification code for both cases
        short_code = supabase_client.generate_short_verification_code(user_id, length=6)

        if signup_status.get("is_confirmed", False):
            # User already confirmed - send login reminder (magic link + verification code)
            customerio_result = customerio_client.send_signup_reminder_transactional(
                email=resend_data.email,
                name=user_name,
                magic_link_url=magic_link_url,
                verification_code=short_code
            )
            message_text = f"We just sent a new login link and verification code to {resend_data.email}"
        else:
            # User not confirmed yet - send full signup confirmation with verification code
            customerio_result = customerio_client.send_signup_confirmation_transactional(
                email=resend_data.email,
                name=user_name,
                magic_link_url=magic_link_url,
                verification_code=short_code
            )
            message_text = f"We just sent a new login url and verification code to {resend_data.email}"

        if not customerio_result["success"]:
            logger.error(
                f"Customer.io resend email failed: {customerio_result.get('error')}"
            )
            raise HTTPException(status_code=500, detail="Failed to send email")

        return AuthResponse(success=True, message=message_text)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend magic link error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/auth/me", tags=["Authentication"])
@limiter.limit("60/minute")
async def get_current_user_info(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get current user information from session"""

    try:
        # Get basic info from session
        user_email = request.session.get("user_email", "")

        return {"id": user_id, "email": user_email}

    except Exception as e:
        logger.error(f"Get current user error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user information")


@app.post(
    "/api/v1/auth/exchange",
    response_model=CodeExchangeResponse,
    tags=["Authentication"],
)
@limiter.limit("20/minute")
async def exchange_code_for_session(
    code_request: CodeExchangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Exchange authorization code for server session"""

    try:
        logger.info(
            f"Code exchange request received for code: {code_request.code[:20]}..."
        )  # Log first 20 chars

        # Validate required fields
        if not code_request.code:
            raise HTTPException(
                status_code=400, detail="Authorization code is required"
            )

        # Exchange code with Supabase
        result = supabase_client.exchange_code_for_session(code_request.code)

        if not result["success"]:
            logger.warning(f"Code exchange failed: {result.get('error')}")
            return CodeExchangeResponse(
                ok=False, error=result.get("error", "Failed to exchange code")
            )

        user = result["user"]
        user_id = user.id
        user_email = user.email

        logger.info(f"Code exchange successful for user {user_id}")

        # Create server session
        request.session["user_id"] = user_id
        request.session["user_email"] = user_email
        request.session["authenticated"] = True

        # Create signup tracking record and mark as confirmed (for JWT authentication)
        try:
            # First check if tracking record already exists
            existing_tracking = supabase_client.get_signup_tracking_by_user_id(user_id)

            if not existing_tracking["success"] or not existing_tracking.get("data"):
                # No existing tracking record, create one
                user_name = f"{user.user_metadata.get('first_name', '')} {user.user_metadata.get('last_name', '')}".strip()
                if not user_name:
                    user_name = user_email.split("@")[0]  # Fallback to email username

                tracking_result = supabase_client.create_signup_tracking(
                    user_id=user_id, email=user_email, name=user_name
                )

                if tracking_result["success"]:
                    logger.info(
                        f"Created signup tracking record for JWT authenticated user {user_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to create signup tracking: {tracking_result.get('error')}"
                    )
            else:
                logger.info(
                    f"Signup tracking already exists for JWT authenticated user {user_id}"
                )

            # Now mark signup as confirmed
            confirmation_result = supabase_client.mark_signup_confirmed(user_id)
            if confirmation_result["success"]:
                logger.info(f"Marked signup confirmed via JWT token exchange for user {user_id}")

                # Add signup_confirmed attribute to Customer.io
                try:
                    customerio_result = customerio_client.update_user_attributes(
                        user_id=user_id,
                        email=user_email,
                        attributes={"signup_confirmed": True}
                    )
                    if customerio_result["success"]:
                        logger.info(f"Customer.io: Added signup_confirmed attribute for {user_email}")
                    else:
                        logger.warning(f"Customer.io: Failed to add signup_confirmed: {customerio_result.get('error')}")
                except Exception as e:
                    logger.warning(f"Customer.io signup_confirmed tracking error (non-fatal): {str(e)}")
            else:
                logger.warning(
                    f"Failed to mark signup confirmed: {confirmation_result.get('error')}"
                )
        except Exception as e:
            logger.warning(
                f"Signup confirmation error (non-fatal): {str(e)}", exc_info=True
            )

        # Mark first login
        try:
            login_result = supabase_client.mark_first_login(user_id)
            if login_result["success"]:
                logger.info(f"Marked first login for user {user_id}")
        except Exception as e:
            logger.warning(
                f"First login marking error (non-fatal): {str(e)}", exc_info=True
            )

        # Create 90-day refresh token for persistent login
        try:
            user_agent = request.headers.get("User-Agent")
            ip_address = request.client.host if request.client else None

            refresh_token = RefreshTokenManager.create_refresh_token(
                db=db,
                user_id=user_id,
                user_agent=user_agent,
                ip_address=ip_address,
                days_valid=90,
            )

            # Set refresh token as HttpOnly cookie
            refresh_token_max_age = 90 * 24 * 60 * 60  # 90 days in seconds
            origin = request.headers.get("origin")
            is_localhost_request = origin and (
                "localhost" in origin or "127.0.0.1" in origin
            )

            # Configure cookie security based on environment
            if is_localhost_request:
                cookie_secure = False  # Allow HTTP for localhost
                cookie_samesite = "lax"
            else:
                cookie_secure = True  # Always secure for production
                cookie_samesite = "none"  # Required for cross-origin

            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=refresh_token_max_age,
                httponly=True,
                secure=cookie_secure,
                samesite=cookie_samesite,
                domain=None,
            )

            logger.info(
                f"Created refresh token for user {user_id} (secure={cookie_secure}, samesite={cookie_samesite})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to create refresh token (non-fatal): {str(e)}", exc_info=True
            )

        return CodeExchangeResponse(ok=True, message="Authentication successful")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Code exchange error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/auth/refresh-session",
    response_model=RefreshSessionResponse,
    tags=["Authentication"],
)
@limiter.limit("20/minute")
async def refresh_user_session(
    request: Request, response: Response, db: Session = Depends(get_db)
):
    """Refresh user session using 90-day refresh token"""

    try:
        logger.info("=" * 60)
        logger.info("Session refresh request received")
        logger.info(f"Request method: {request.method}")
        logger.info(f"Request URL: {request.url}")

        # Get refresh token from HttpOnly cookie
        refresh_token = request.cookies.get("refresh_token")

        # Debug: Log all cookies and headers
        logger.info(f"All cookies received: {dict(request.cookies)}")
        logger.info(f"Cookie count: {len(request.cookies)}")
        logger.info(f"Request headers:")
        logger.info(f"  - Origin: {request.headers.get('origin')}")
        logger.info(f"  - Referer: {request.headers.get('referer')}")
        logger.info(f"  - Cookie header present: {'cookie' in request.headers}")
        logger.info(f"  - User-Agent: {request.headers.get('user-agent', '')[:50]}")

        if not refresh_token:
            logger.warning("❌ No refresh token found in cookies")
            logger.warning(f"Available cookie keys: {list(request.cookies.keys())}")
            return RefreshSessionResponse(ok=False, error="No refresh token found")

        # Validate refresh token
        logger.info(f"Validating refresh token (length: {len(refresh_token)})")
        token_info = RefreshTokenManager.validate_refresh_token(db, refresh_token)

        if not token_info:
            logger.warning("❌ Invalid or expired refresh token")
            # Clear invalid cookie
            response.delete_cookie("refresh_token")
            return RefreshSessionResponse(
                ok=False, error="Invalid or expired refresh token"
            )

        user_id = token_info["user_id"]
        logger.info(f"✅ Refresh token valid for user {user_id}")
        logger.info(f"Token expires at: {token_info.get('expires_at')}")

        # Get user info from Supabase
        try:
            logger.info(f"Fetching user data from Supabase for user {user_id}")
            user_data = supabase_client.service_client.auth.admin.get_user_by_id(
                user_id
            )
            if not user_data or not user_data.user:
                logger.error(f"❌ User not found in Supabase: {user_id}")
                return RefreshSessionResponse(ok=False, error="User not found")
            user_email = user_data.user.email
            logger.info(f"✅ User data retrieved: {user_email}")
        except Exception as e:
            logger.error(f"❌ Failed to get user data: {str(e)}")
            return RefreshSessionResponse(ok=False, error="Failed to validate user")

        # Create new session
        logger.info("Creating new session")
        request.session["user_id"] = user_id
        request.session["user_email"] = user_email
        request.session["authenticated"] = True
        logger.info("✅ Session created successfully")

        # Create new refresh token (token rotation for security)
        try:
            # Revoke old token
            RefreshTokenManager.revoke_refresh_token(db, refresh_token)

            # Create new token
            user_agent = request.headers.get("User-Agent")
            ip_address = request.client.host if request.client else None

            new_refresh_token = RefreshTokenManager.create_refresh_token(
                db=db,
                user_id=user_id,
                user_agent=user_agent,
                ip_address=ip_address,
                days_valid=90,
            )

            # Set new refresh token as HttpOnly cookie
            refresh_token_max_age = 90 * 24 * 60 * 60  # 90 days in seconds
            origin = request.headers.get("origin")
            is_localhost_request = origin and (
                "localhost" in origin or "127.0.0.1" in origin
            )

            # For cross-origin requests, always use SameSite=None with Secure=True
            if is_localhost_request:
                # For localhost development
                cookie_secure = False  # Allow HTTP for localhost
                cookie_samesite = "lax"  # Use lax for same-site localhost
            else:
                # For cross-origin deployed requests
                cookie_secure = True  # Always secure for cross-origin
                cookie_samesite = "none"  # Required for cross-origin

            logger.info(
                f"Setting cookie: origin={origin}, is_localhost={is_localhost_request}, secure={cookie_secure}, samesite={cookie_samesite}"
            )

            response.set_cookie(
                key="refresh_token",
                value=new_refresh_token,
                max_age=refresh_token_max_age,
                httponly=True,
                secure=cookie_secure,
                samesite=cookie_samesite,
                domain=None,  # Let browser handle domain automatically
            )

            logger.info(
                f"Rotated refresh token cookie with secure={cookie_secure}, samesite={cookie_samesite}, httponly=True"
            )

            logger.info(f"✅ Rotated refresh token for user {user_id}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to rotate refresh token (non-fatal): {str(e)}")

        logger.info("✅ Session refresh completed successfully")
        logger.info("=" * 60)
        return RefreshSessionResponse(ok=True, message="Session refreshed successfully")

    except Exception as e:
        logger.error(f"❌ Session refresh error: {str(e)}")
        logger.error("=" * 60)
        return RefreshSessionResponse(ok=False, error="Internal server error")


@app.post("/api/v1/auth/callback", tags=["Authentication"])
async def auth_callback(request: Request, response: Response, db: Session = Depends(get_db)):
    """Handle magic link callback - exchange access token for session"""

    try:
        # Get access token and refresh token from request body
        body = await request.json()
        access_token = body.get("access_token")
        refresh_token_from_hash = body.get("refresh_token")

        if not access_token:
            logger.warning("Auth callback missing access_token")
            return {"success": False, "error": "Missing access_token"}

        logger.info(f"Auth callback received access_token: {access_token[:20]}...")

        # Validate the JWT access token and get user info
        # The exchange_code_for_session method already handles JWT tokens
        result = supabase_client.exchange_code_for_session(access_token)

        if not result["success"]:
            logger.warning(f"Token validation failed in callback: {result.get('error')}")
            return {"success": False, "error": "Token validation failed"}

        user = result["user"]
        user_id = user.id
        user_email = user.email

        logger.info(f"Auth callback successful for user {user_id}")

        # Create server session
        request.session["user_id"] = user_id
        request.session["user_email"] = user_email
        request.session["authenticated"] = True

        # Mark first login and signup confirmation (same as verify-code endpoint)
        try:
            # Create/update signup tracking
            existing_tracking = supabase_client.get_signup_tracking_by_user_id(user_id)

            if not existing_tracking["success"] or not existing_tracking.get("data"):
                user_name = f"{user.user_metadata.get('first_name', '')} {user.user_metadata.get('last_name', '')}".strip()
                if not user_name:
                    user_name = user_email.split('@')[0]

                tracking_result = supabase_client.create_signup_tracking(
                    user_id=user_id,
                    email=user_email,
                    name=user_name
                )
                if tracking_result["success"]:
                    logger.info(f"Created signup tracking for user {user_id}")

            # Mark signup confirmed
            confirmation_result = supabase_client.mark_signup_confirmed(user_id)
            if confirmation_result.get("success"):
                logger.info(f"Marked signup confirmed via auth callback for user {user_id}")

                # Add signup_confirmed attribute to Customer.io
                try:
                    customerio_result = customerio_client.update_user_attributes(
                        user_id=user_id,
                        email=user_email,
                        attributes={"signup_confirmed": True}
                    )
                    if customerio_result["success"]:
                        logger.info(f"Customer.io: Added signup_confirmed attribute for {user_email}")
                    else:
                        logger.warning(f"Customer.io: Failed to add signup_confirmed: {customerio_result.get('error')}")
                except Exception as e:
                    logger.warning(f"Customer.io signup_confirmed tracking error (non-fatal): {str(e)}")

            # Mark first login
            supabase_client.mark_first_login(user_id)
        except Exception as e:
            logger.warning(f"Signup tracking error (non-fatal): {str(e)}")

        # Invalidate caches (same as verify-code endpoint)
        try:
            favorite_podcasts = await podcast_service.get_user_favorite_podcasts(user_id)
            if favorite_podcasts:
                for podcast in favorite_podcasts:
                    podcast_id = podcast.get('id')
                    if podcast_id:
                        podcast_service.episode_cache.invalidate_podcast(podcast_id)
        except Exception as e:
            logger.warning(f"Failed to invalidate episode cache (non-fatal): {str(e)}")

        try:
            from user_profile_cache_service import get_user_profile_cache_service
            profile_cache = get_user_profile_cache_service()
            profile_cache.invalidate(user_id)
        except Exception as e:
            logger.warning(f"Failed to invalidate profile cache (non-fatal): {str(e)}")

        # Create refresh token
        try:
            user_agent = request.headers.get("User-Agent")
            ip_address = request.client.host if request.client else None

            refresh_token = RefreshTokenManager.create_refresh_token(
                db=db,
                user_id=user_id,
                user_agent=user_agent,
                ip_address=ip_address,
                days_valid=90
            )

            # Set refresh token cookie with appropriate security settings
            refresh_token_max_age = 90 * 24 * 60 * 60

            # Determine cookie security settings based on origin
            origin = request.headers.get("origin")
            is_localhost_request = origin and (
                origin.startswith("http://localhost") or
                origin.startswith("http://127.0.0.1")
            )

            if is_localhost_request:
                cookie_secure = False  # Cannot use Secure on HTTP
                cookie_samesite = "lax"  # Lax works for same-site localhost
            else:
                cookie_secure = True  # Always secure for production
                cookie_samesite = "none"  # Required for cross-origin

            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=refresh_token_max_age,
                httponly=True,
                secure=cookie_secure,
                samesite=cookie_samesite,
                domain=None
            )
            logger.info(f"Set refresh token cookie for user {user_id} (secure={cookie_secure}, samesite={cookie_samesite})")
        except Exception as e:
            logger.warning(f"Failed to create refresh token (non-fatal): {str(e)}")

        # Determine redirect path based on user status
        redirect_path = "/claim-podcast"  # Default safe fallback

        try:
            # Get user status to determine correct redirect
            # 1. Get onboarding status
            onboarding_result = supabase_client.get_onboarding_data(user_id)
            onboarding_completed = False

            if onboarding_result["success"] and onboarding_result["data"]:
                onboarding_data = onboarding_result["data"][0] if onboarding_result["data"] else {}
                onboarding_completed = onboarding_data.get("is_completed", False)

            # 2. Get podcast claim status
            podcast_claims_result = supabase_client.get_user_podcast_claims_session(user_id)
            podcast_claimed = False

            if podcast_claims_result["success"] and podcast_claims_result["data"]:
                claims = podcast_claims_result["data"]
                for claim in claims:
                    if claim.get("is_verified", False):
                        podcast_claimed = True
                        break

            # 3. Apply redirect logic
            if not podcast_claimed and not onboarding_completed:
                redirect_path = "/claim-podcast"
                logger.info(f"User {user_id} → /claim-podcast (no claim, no onboarding)")
            elif podcast_claimed and not onboarding_completed:
                redirect_path = "/onboarding"
                logger.info(f"User {user_id} → /onboarding (claimed, needs onboarding)")
            elif podcast_claimed and onboarding_completed:
                redirect_path = "/home/my-feed"
                logger.info(f"User {user_id} → /home/my-feed (claimed and onboarded)")
            else:
                # Edge case: no claim but onboarding complete - still send to claim
                redirect_path = "/claim-podcast"
                logger.info(f"User {user_id} → /claim-podcast (edge case: onboarded but no claim)")

        except Exception as e:
            logger.warning(f"Failed to determine user status (defaulting to claim-podcast): {str(e)}")
            redirect_path = "/claim-podcast"

        return {
            "success": True,
            "redirect_path": redirect_path,
            "user_id": user_id
        }

    except Exception as e:
        logger.error(f"Auth callback error: {str(e)}")
        return {"success": False, "error": "Authentication failed"}


@app.get("/api/v1/auth/check", tags=["Authentication"])
async def check_auth(request: Request):
    """Lightweight auth check - just returns 200 if authenticated"""
    try:
        user_id = get_current_user_from_session(request)
        return {"authenticated": True, "user_id": user_id}
    except HTTPException:
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.get(
    "/api/v1/auth/user-status",
    response_model=UserStatusResponse,
    tags=["Authentication"],
)
@limiter.limit("30/minute")
async def get_user_status(request: Request):
    """Get comprehensive user status including authentication, onboarding, and verification progress"""

    try:
        # Check if user is authenticated
        user_id = request.session.get("user_id")
        user_email = request.session.get("user_email")

        if not user_id:
            # User not authenticated
            return UserStatusResponse(
                user_id=None,
                email=None,
                signup_confirmed=False,
                has_logged_in=False,
                onboarding_completed=False,
                current_onboarding_step=0,
                onboarding_steps_completed={},
                podcast_claim_sent=False,
                podcast_claim_verified=False,
                subscription_plan="free",
                overall_status="needs_authentication",
            )

        # User is authenticated - gather comprehensive status

        # 1. Get signup confirmation status
        signup_tracking = supabase_client.get_signup_tracking_by_user_id(user_id)
        signup_confirmed = False
        has_logged_in = False

        if signup_tracking["success"] and signup_tracking["data"]:
            signup_confirmed = signup_tracking["data"].get("signup_confirmed", False)
            has_logged_in = signup_tracking["data"].get("has_logged_in", False)

        # 2. Get onboarding status
        onboarding_result = supabase_client.get_onboarding_data(user_id)
        onboarding_completed = False
        current_onboarding_step = 1
        onboarding_steps_completed = {
            "step_1": False,
            "step_2": False,
            "step_3": False,
            "step_4": False,
            "step_5": False,
        }

        if onboarding_result["success"] and onboarding_result["data"]:
            onboarding_data = (
                onboarding_result["data"][0] if onboarding_result["data"] else {}
            )
            onboarding_completed = onboarding_data.get("is_completed", False)
            current_onboarding_step = onboarding_data.get("current_step", 1)

            # Map onboarding steps
            onboarding_steps_completed = {
                "step_1": onboarding_data.get("step_1_completed", False),
                "step_2": onboarding_data.get("step_2_completed", False),
                "step_3": onboarding_data.get("step_3_completed", False),
                "step_4": onboarding_data.get("step_4_completed", False),
                "step_5": onboarding_data.get("step_5_completed", False),
            }

        # 3. Get podcast claims status
        podcast_claims_result = supabase_client.get_user_podcast_claims_session(user_id)
        podcast_claim_sent = False
        podcast_claim_verified = False

        if podcast_claims_result["success"] and podcast_claims_result["data"]:
            claims = podcast_claims_result["data"]

            for claim in claims:
                if claim.get("is_verified", False):
                    podcast_claim_verified = True
                    podcast_claim_sent = True  # If verified, it was definitely sent
                elif claim.get("claim_status") == "pending":
                    podcast_claim_sent = True

        # 4. Get subscription status
        from access_control import get_access_control

        ac = get_access_control()
        subscription = ac.get_user_subscription_plan(user_id)
        subscription_plan = subscription.get("plan_name", "free")

        # 5. Determine overall status
        overall_status = "complete"

        if not signup_confirmed:
            overall_status = "needs_confirmation"
        elif not onboarding_completed:
            overall_status = "needs_onboarding"
        elif podcast_claim_sent and not podcast_claim_verified:
            overall_status = "pending_podcast_verification"
        else:
            overall_status = "complete"

        return UserStatusResponse(
            user_id=user_id,
            email=user_email,
            signup_confirmed=signup_confirmed,
            has_logged_in=has_logged_in,
            onboarding_completed=onboarding_completed,
            current_onboarding_step=current_onboarding_step,
            onboarding_steps_completed=onboarding_steps_completed,
            podcast_claim_sent=podcast_claim_sent,
            podcast_claim_verified=podcast_claim_verified,
            subscription_plan=subscription_plan,
            overall_status=overall_status,
        )

    except Exception as e:
        logger.error(f"Get user status error: {str(e)}")
        # Return safe default state on error
        return UserStatusResponse(
            user_id=None,
            email=None,
            signup_confirmed=False,
            has_logged_in=False,
            onboarding_completed=False,
            current_onboarding_step=1,
            onboarding_steps_completed={
                "step_1": False,
                "step_2": False,
                "step_3": False,
                "step_4": False,
                "step_5": False,
                "step_6": False,
            },
            podcast_claim_sent=False,
            podcast_claim_verified=False,
            subscription_plan="free",
            overall_status="error",
        )


@app.post("/api/v1/auth/logout", tags=["Authentication"])
@limiter.limit("20/minute")
async def logout_user(request: Request, response: Response):
    """Logout user by clearing session"""

    try:
        logger.info("Logout request received")

        # Get user ID from session if available
        user_id = request.session.get("user_id")

        # Clear server session
        request.session.clear()

        # Clear session cookie
        response.delete_cookie("session")

        if user_id:
            logger.info(f"User {user_id} logged out successfully")

        return {"ok": True, "message": "Logged out successfully"}

    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return {"ok": False, "error": "Internal server error"}


# Podcast Endpoints
@app.get(
    "/api/v1/podcasts/typeahead", response_model=PodcastSearchResults, tags=["Podcasts"]
)
@limiter.limit("30/minute")
async def typeahead_search_podcasts(
    request: Request,
    q: str,
    limit: int = 10,
    user_id: str = Depends(get_current_user_from_session),
):
    """Typeahead search for podcasts - fast suggestions for autocomplete"""

    # Validate and sanitize search query
    try:
        sanitized_query = validate_search_query(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if limit > 20:
        limit = 20  # Cap the limit for typeahead

    try:
        result = listennotes_client.typeahead_search(sanitized_query, limit)

        if result["success"]:
            return PodcastSearchResults(
                results=result["results"], total=result["total"]
            )
        else:
            error_msg = result.get("error", "Typeahead search failed")
            raise HTTPException(
                status_code=500, detail=f"Typeahead search failed: {error_msg}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Typeahead search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/podcasts/search", response_model=ClaimResponse, tags=["Podcasts"])
@limiter.limit("5/minute")
async def search_and_claim_podcast(
    request: Request, q: str, user_id: str = Depends(get_current_user_from_session)
):
    """Search for podcast and initiate claim process - supports both podcast names and RSS URLs"""

    # Check if user has confirmed their signup
    signup_check = supabase_client.check_user_signup_confirmed(user_id)
    if not signup_check["success"] or not signup_check.get("is_confirmed", False):
        raise HTTPException(
            status_code=403,
            detail="Please confirm your signup before claiming podcasts",
        )

    podcast_title = None
    podcast_data = None

    # Detect if query is an RSS URL or plain text search
    if is_rss_url(q):
        # Handle RSS URL - parse feed to get title, then search ListenNotes
        try:
            logger.info(f"Parsing RSS feed for claim: {sanitize_for_log(q)}")
            rss_result = rss_parser.parse_rss_feed(q)

            if not rss_result["success"]:
                error_msg = rss_result.get("error", "Unknown error")
                if (
                    "syntax error" in error_msg.lower()
                    or "webpage" in error_msg.lower()
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid RSS feed URL. {error_msg} Please provide the direct RSS/XML feed URL, not a webpage URL.",
                    )
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Failed to parse RSS feed: {error_msg}"
                    )

            podcast_title = rss_result["podcast_info"].get("title", "")
            if not podcast_title:
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract podcast title from RSS feed",
                )

            logger.info(
                f"Extracted podcast title from RSS: {sanitize_for_log(podcast_title)}"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"RSS feed parsing error: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to parse RSS feed")

    else:
        # Handle plain text search - use as title directly
        try:
            podcast_title = validate_search_query(q)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Search ListenNotes for exact podcast match using the title
    try:
        logger.info(
            f"Searching ListenNotes for podcast: {sanitize_for_log(podcast_title)}"
        )
        # Try typeahead first since it's more reliable for finding podcasts
        search_result = listennotes_client.typeahead_search(podcast_title, limit=10)

        # If typeahead fails, returns no results, or results don't have email addresses, fall back to regular search
        typeahead_has_email = False
        if search_result.get("success") and search_result.get("results"):
            # Check if any result has an email address
            for result in search_result.get("results", []):
                if result.get("email"):
                    typeahead_has_email = True
                    break

        if (
            not search_result.get("success")
            or not search_result.get("results")
            or not typeahead_has_email
        ):
            if not typeahead_has_email and search_result.get("results"):
                logger.info(
                    f"Typeahead found results but no email addresses, falling back to regular search for: {podcast_title}"
                )
            else:
                logger.info(
                    f"Typeahead failed, falling back to regular search for: {podcast_title}"
                )
            search_result = listennotes_client.search_podcasts(podcast_title, limit=10)

        if not search_result["success"]:
            error_msg = search_result.get("error", "Unknown search error")
            if "timeout" in error_msg.lower():
                raise HTTPException(
                    status_code=503,
                    detail="Search service temporarily unavailable. Please try again in a moment.",
                )
            else:
                raise HTTPException(
                    status_code=503, detail=f"Search service error: {error_msg}"
                )

        if not search_result.get("results"):
            logger.warning(
                f"ListenNotes search returned no results for: {podcast_title}. Search result: {search_result}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No podcasts found matching '{podcast_title}'. Try a different search term or check the spelling.",
            )

        # Find best title match (try exact first, then fuzzy)
        podcast_data = None
        search_results = search_result["results"]

        # First try exact match (case-insensitive)
        for result in search_results:
            if result.get("title", "").lower() == podcast_title.lower():
                podcast_data = result
                break

        # If no exact match, try fuzzy matching (contains all words)
        if not podcast_data:
            query_words = set(podcast_title.lower().split())
            for result in search_results:
                title_words = set(result.get("title", "").lower().split())
                # Check if all query words are in the title
                if query_words.issubset(title_words):
                    podcast_data = result
                    break

        # If still no match, use the first result
        if not podcast_data and search_results:
            podcast_data = search_results[0]
            logger.info(
                f"Using first search result: {sanitize_for_log(podcast_data.get('title', ''))}"
            )

        if not podcast_data:
            raise HTTPException(
                status_code=404,
                detail=f"No suitable podcast found for '{podcast_title}'. Please try a more specific search term.",
            )

        # Verify podcast has contact email
        podcast_email = podcast_data.get("email", "")
        if not podcast_email:
            raise HTTPException(
                status_code=400,
                detail="This podcast does not have a contact email address in our database",
            )

        listennotes_id = podcast_data.get("id", "")
        if not listennotes_id:
            raise HTTPException(
                status_code=400, detail="Invalid podcast data from ListenNotes"
            )

        logger.info(
            f"Found podcast: {sanitize_for_log(podcast_data.get('title', ''))} with email: {sanitize_for_log(podcast_email)}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ListenNotes search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to search for podcast")

    # Check if podcast already claimed by another user
    try:
        existing_claim_check = supabase_client.check_podcast_already_claimed(
            listennotes_id, user_id
        )

        if not existing_claim_check["success"]:
            raise HTTPException(
                status_code=500, detail="Failed to check existing claims"
            )

        if existing_claim_check.get("claimed", False):
            claimed_by_current_user = existing_claim_check.get(
                "claimed_by_current_user", False
            )
            if claimed_by_current_user:
                raise HTTPException(
                    status_code=409, detail="You have already claimed this podcast"
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail="This podcast has already been claimed by another user",
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Existing claim check error: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to verify podcast claim status"
        )

    # Generate verification code and create claim
    try:
        import secrets

        verification_code = secrets.randbelow(900000) + 100000  # 6-digit code
        expiry_hours = get_verification_code_expiry_hours()

        # Create podcast claim in Supabase
        claim_result = supabase_client.create_podcast_claim(
            user_id=user_id,
            listennotes_id=listennotes_id,
            podcast_title=podcast_data["title"],
            podcast_email=podcast_email,
            verification_code=str(verification_code),
            expiry_hours=expiry_hours,
        )

        if not claim_result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create podcast claim: {claim_result.get('error', 'Unknown error')}",
            )

        claim_id = claim_result.get("claim_id")
        logger.info(f"Created podcast claim {claim_id} for user {user_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Claim creation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create podcast claim")

    # Send verification email to podcast owner
    try:
        user_name = get_user_display_name(user_id)

        # Determine email recipient based on environment
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "dev":
            # Use development override email
            recipient_email = os.getenv(
                "DEV_PODCAST_CLAIM_EMAIL", "damiokuneye@gmail.com"
            )
            logger.info(
                f"Development mode: sending podcast claim email to {recipient_email} instead of {podcast_email}"
            )
        else:
            # Use actual podcast email in production
            recipient_email = podcast_email
            logger.info(
                f"Production mode: sending podcast claim email to actual podcast owner {podcast_email}"
            )

        email_result = customerio_client.send_podcast_claim_intent_transactional(
            email=recipient_email,
            name=user_name,
            podcast_title=podcast_data["title"],
            verification_code=str(verification_code),
        )

        if not email_result["success"]:
            logger.warning(
                f"Failed to send claim intent email: {email_result.get('error', 'Unknown error')}"
            )
            # Don't fail the entire request - the claim was created successfully

        logger.info(
            f"Sent claim intent email to {sanitize_for_log(podcast_email)} for claim {claim_id}"
        )

    except Exception as e:
        logger.warning(f"Email sending error (non-fatal): {str(e)}")
        # Don't fail the entire request

    return ClaimResponse(
        success=True,
        message=f"Verification code sent to {podcast_email}. Please check your email and use the code to verify your claim.",
        claim_id=claim_id,
    )


@app.post(
    "/api/v1/podcasts/verify-claim", response_model=ClaimResponse, tags=["Podcasts"]
)
@limiter.limit("10/minute")
async def verify_podcast_claim_by_code(
    verify_data: VerifyClaimByCodeRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Verify podcast claim using just verification code (user-friendly endpoint)"""

    if not verify_data.verification_code:
        raise HTTPException(status_code=400, detail="Verification code is required")

    # Validate code format (6 digits)
    if (
        not verify_data.verification_code.isdigit()
        or len(verify_data.verification_code) != 6
    ):
        raise HTTPException(
            status_code=400, detail="Verification code must be 6 digits"
        )

    try:
        # Use the new user-friendly verification method
        result = supabase_client.verify_podcast_claim_by_email(
            user_id, verify_data.verification_code
        )

        if result["success"]:
            claim_id = result.get("claim_id")
            podcast_title = result.get("podcast_title")

            # Get user info for notifications
            try:
                user_data = supabase_client.service_client.auth.admin.get_user_by_id(
                    user_id
                )
                user_email = (
                    user_data.user.email if user_data and user_data.user else None
                )
            except Exception as e:
                logger.warning(f"Could not get user email for notifications: {str(e)}")
                user_email = None

            # Mark podcast claim as completed in user onboarding (using session-based auth)
            if user_email:
                try:
                    # For session-based auth, we need to create a temporary user token or use service client
                    # Since we're in session context, we'll use service client directly
                    onboarding_update = (
                        supabase_client.service_client.table("user_onboarding")
                        .update(
                            {
                                "podcast_claim_completed": True,
                                "has_verified_podcast_claims": True,
                                "claimed_podcast_title": podcast_title,
                            }
                        )
                        .eq("id", user_id)
                        .execute()
                    )

                    if onboarding_update.data:
                        logger.info(f"Updated onboarding for user {user_id}")
                    else:
                        logger.warning(
                            f"Failed to update onboarding for user {user_id}"
                        )
                except Exception as e:
                    logger.warning(f"Onboarding update error (non-fatal): {str(e)}")

                # Add verified_podcast attribute to Customer.io
                try:
                    customerio_result = customerio_client.update_user_attributes(
                        user_id=user_id,
                        email=user_email,
                        attributes={"verified_podcast": True}
                    )
                    if customerio_result["success"]:
                        logger.info(f"Customer.io: Added verified_podcast attribute for {user_email}")
                    else:
                        logger.warning(f"Customer.io: Failed to add verified_podcast: {customerio_result.get('error')}")
                except Exception as e:
                    logger.warning(f"Customer.io verified_podcast tracking error (non-fatal): {str(e)}")

            # Send success notification
            if user_email:
                user_name = get_user_display_name(user_id, user_email)
                success_email = (
                    customerio_client.send_podcast_claim_success_transactional(
                        email=user_email, name=user_name, podcast_title=podcast_title
                    )
                )
                if success_email["success"]:
                    logger.info(f"Sent podcast claim success email to {user_email}")
                else:
                    logger.error(
                        f"Failed to send success email: {success_email.get('error')}"
                    )

            return ClaimResponse(
                success=True,
                message=f"Podcast claim for '{podcast_title}' verified successfully!",
                claim_id=claim_id,
            )
        else:
            error_msg = result.get("error", "Verification failed")
            if "Invalid verification code" in error_msg:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid verification code or no pending claims found",
                )
            elif "expired" in error_msg.lower():
                raise HTTPException(
                    status_code=400, detail="Verification code has expired"
                )
            else:
                raise HTTPException(
                    status_code=500, detail=f"Verification failed: {error_msg}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Podcast claim verification by code error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Onboarding Endpoints
@app.post(
    "/api/v1/onboarding/profile", response_model=OnboardingResponse, tags=["Onboarding"]
)
@limiter.limit("5/minute")
async def save_onboarding_profile(
    onboarding_data: OnboardingRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Save user onboarding data"""

    # Validate required fields
    if (
        not onboarding_data.podcasting_experience
        or not onboarding_data.category_ids
        or not onboarding_data.location_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Podcasting experience, category_ids, and location_id are required",
        )

    # Validate podcasting experience value
    valid_experiences = ["0-1_year", "1-3_years", "3_years_plus"]
    if onboarding_data.podcasting_experience not in valid_experiences:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid podcasting experience. Must be one of: {', '.join(valid_experiences)}",
        )

    try:
        # Prepare onboarding data
        data = {
            "podcasting_experience": onboarding_data.podcasting_experience,
            "category_ids": onboarding_data.category_ids,
            "location_id": onboarding_data.location_id,
            "network_name": onboarding_data.network_name,
            "is_part_of_network": onboarding_data.is_part_of_network,
            "looking_for_guests": onboarding_data.looking_for_guests,
            "wants_to_be_guest": onboarding_data.wants_to_be_guest,
            "favorite_podcast_ids": onboarding_data.favorite_podcast_ids,
        }

        # Save to Supabase using service client for session-based auth
        result = supabase_client.save_onboarding_data(user_id, data, user_token=None)

        if result["success"]:
            return OnboardingResponse(
                success=True, message="Onboarding profile saved successfully"
            )
        else:
            error_msg = result.get("error", "Failed to save onboarding data")
            raise HTTPException(status_code=500, detail=f"Save failed: {error_msg}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Onboarding save error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/podcasts/my-claims", response_model=dict, tags=["Podcasts"])
@limiter.limit("20/minute")
async def get_my_podcast_claims(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get current user's podcast claims"""

    try:
        claims_result = supabase_client.get_user_podcast_claims_session(user_id)

        if claims_result["success"]:
            return {
                "success": True,
                "claims": claims_result["data"] or [],
                "total": len(claims_result["data"] or []),
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get claims: {claims_result.get('error')}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get podcast claims error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# @app.post("/api/v1/admin/fix-podcast-claim-status", response_model=dict, tags=["Admin"])
# @limiter.limit("5/minute")
# async def fix_podcast_claim_status(request: Request, _: None = Depends(require_localhost), user_id: str = Depends(get_current_user_from_session)):
#     """Fix podcast claim status in onboarding table (admin endpoint)"""
#
#     try:
#         # Check if user has verified claims
#         claims_result = supabase_client.get_user_podcast_claims_session(user_id)
#
#         if not claims_result["success"]:
#             raise HTTPException(status_code=500, detail="Failed to get claims")
#
#         verified_claims = []
#         for claim in claims_result["data"] or []:
#             if claim.get("is_verified", False) and claim.get("claim_status") == "verified":
#                 verified_claims.append(claim)
#
#         if not verified_claims:
#             return {"success": False, "message": "No verified podcast claims found"}
#
#         # Update onboarding table to reflect the verified claim
#         latest_claim = verified_claims[0]  # Use the first verified claim
#
#         update_result = supabase_client.service_client.table("user_onboarding").upsert({
#             "id": user_id,
#             "podcast_claim_completed": True,
#             "has_verified_podcast_claims": True,
#             "claimed_podcast_title": latest_claim.get("podcast_title")
#         }).execute()
#
#         if update_result.data:
#             return {
#                 "success": True,
#                 "message": f"Fixed podcast claim status for '{latest_claim.get('podcast_title')}'",
#                 "verified_claims": len(verified_claims)
#             }
#         else:
#             raise HTTPException(status_code=500, detail="Failed to update onboarding status")
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Fix podcast claim status error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Failed to fix status: {str(e)}")

# @app.get("/api/v1/admin/debug-featured", response_model=dict, tags=["Admin"])
# @limiter.limit("10/minute")
# async def debug_featured_podcasts(request: Request, _: None = Depends(require_localhost), user_id: str = Depends(get_current_user_from_session)):
#     """Debug featured podcasts table (admin endpoint)"""
#
#     try:
#         if not supabase_client.service_client:
#             raise HTTPException(status_code=500, detail="Service client not available")
#
#         # Check featured podcasts in main podcasts table
#         try:
#             result = supabase_client.service_client.table("podcasts") \
#                 .select("*") \
#                 .eq("is_featured", True) \
#                 .order("featured_priority", desc=True) \
#                 .limit(10) \
#                 .execute()
#
#             return {
#                 "success": True,
#                 "featured_podcasts": {
#                     "count": len(result.data) if result.data else 0,
#                     "data": result.data[:3] if result.data else []  # First 3 records
#                 }
#             }
#
#         except Exception as e:
#             return {
#                 "success": False,
#                 "error": f"Featured podcasts error: {str(e)}"
#             }
#
#     except Exception as e:
#         logger.error(f"Debug featured podcasts error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Debug failed: {str(e)}")


@app.get(
    "/api/v1/onboarding/networks", response_model=NetworkResponse, tags=["Onboarding"]
)
@limiter.limit("20/minute")
async def get_podcast_networks(request: Request):
    """Get available podcast networks"""

    # Static list of popular podcast networks
    # In a real application, this could be dynamically sourced
    networks = [
        "NPR",
        "Spotify",
        "Wondery",
        "Gimlet Media",
        "Radiotopia",
        "Midroll Media",
        "Podcast One",
        "Audioboom",
        "Libsyn",
        "Anchor",
        "Stitcher",
        "iHeartMedia",
        "Cumulus Media",
        "Entercom",
        "Westwood One",
        "PodcastOne",
        "Independent",
    ]

    return NetworkResponse(networks=sorted(networks))


@app.get(
    "/api/v1/onboarding/status",
    response_model=OnboardingStatusResponse,
    tags=["Onboarding"],
)
@limiter.limit("20/minute")
async def get_onboarding_status(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get user's onboarding completion status and current step"""

    try:
        # Get onboarding data using session-based auth
        onboarding_result = supabase_client.get_onboarding_data(
            user_id, user_token=None
        )

        # Get podcast claims - need to implement session-based version
        claims_result = supabase_client.get_user_podcast_claims_session(user_id)

        if onboarding_result["success"] and onboarding_result["data"]:
            data = onboarding_result["data"][0]

            steps_completed = {
                "step_1": data.get("step_1_completed", False),
                "step_2": data.get("step_2_completed", False),
                "step_3": data.get("step_3_completed", False),
                "step_4": data.get("step_4_completed", False),
                "step_5": data.get("step_5_completed", False),
                "podcast_claim": data.get("podcast_claim_completed", False),
            }

            current_step = data.get("current_step", 1)
            is_completed = data.get("is_completed", False)
        else:
            # No onboarding data yet - user is at step 1
            steps_completed = {
                "step_1": False,
                "step_2": False,
                "step_3": False,
                "step_4": False,
                "step_5": False,
                "podcast_claim": False,
            }
            current_step = 1
            is_completed = False

        # Check podcast claims status
        has_pending_claims = False
        has_verified_claims = False

        if claims_result["success"] and claims_result["data"]:
            for claim in claims_result["data"]:
                if claim.get("claim_status") == "pending":
                    has_pending_claims = True
                elif claim.get("claim_status") == "verified":
                    has_verified_claims = True

        return OnboardingStatusResponse(
            is_completed=is_completed,
            current_step=current_step,
            steps_completed=steps_completed,
            has_pending_podcast_claims=has_pending_claims,
            has_verified_podcast_claims=has_verified_claims,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get onboarding status error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/onboarding/profile",
    response_model=OnboardingProfileResponse,
    tags=["Onboarding"],
)
@limiter.limit("20/minute")
async def get_onboarding_profile(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get user's current onboarding profile data"""

    # Check if user has verified podcast claim before allowing access to onboarding data
    if not check_user_has_verified_podcast_claim(user_id):
        raise HTTPException(
            status_code=403,
            detail="You must verify a podcast claim before accessing onboarding",
        )

    try:
        result = supabase_client.get_onboarding_data(user_id, user_token=None)

        if result["success"] and result["data"]:
            data = result["data"][0]

            # Clean up the data - remove internal tracking fields
            # TODO: Get category_ids from junction table

            # Get favorite podcasts from the user_podcast_follows table
            favorite_podcast_ids = []
            try:
                favorite_podcasts = await podcast_service.get_user_favorite_podcasts(
                    user_id
                )
                if favorite_podcasts:
                    # Extract just the podcast IDs in chronological order
                    favorite_podcast_ids = [
                        fav.get("id") or fav.get("podcast_id")
                        for fav in favorite_podcasts
                    ]
            except Exception as e:
                logger.warning(
                    f"Failed to get favorite podcasts for user {user_id}: {str(e)}"
                )
                favorite_podcast_ids = []

            profile_data = {
                "podcasting_experience": data.get("podcasting_experience"),
                "category_ids": [],  # Will be populated from junction table
                "location_id": data.get("location_id"),
                "network_name": data.get("network_name"),
                "is_part_of_network": data.get("is_part_of_network"),
                "looking_for_guests": data.get("looking_for_guests"),
                "wants_to_be_guest": data.get("wants_to_be_guest"),
                "favorite_podcast_ids": favorite_podcast_ids,
            }

            return OnboardingProfileResponse(
                success=True,
                data=profile_data,
                is_completed=data.get("is_completed", False),
                current_step=data.get("current_step", 1),
            )
        else:
            # No onboarding data yet
            return OnboardingProfileResponse(
                success=True, data=None, is_completed=False, current_step=1
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get onboarding profile error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/onboarding/step", response_model=OnboardingResponse, tags=["Onboarding"]
)
@limiter.limit("10/minute")
async def save_onboarding_step(
    step_data: OnboardingStepRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Save individual onboarding step data for incremental progress"""

    # Validate step number
    if step_data.step < 1 or step_data.step > 5:
        raise HTTPException(status_code=400, detail="Step must be between 1 and 5")

    # Check if user has verified podcast claim before allowing onboarding
    if not check_user_has_verified_podcast_claim(user_id):
        raise HTTPException(
            status_code=403,
            detail="You must verify a podcast claim before starting onboarding",
        )

    # Check if user has completed previous steps (sequential progression)
    if step_data.step > 1:
        try:
            # Get user's current onboarding status
            onboarding_result = supabase_client.get_onboarding_data(
                user_id, user_token=None
            )

            if onboarding_result["success"] and onboarding_result["data"]:
                data = onboarding_result["data"][0]

                # Check if previous step is completed
                previous_step = step_data.step - 1
                previous_step_completed = data.get(
                    f"step_{previous_step}_completed", False
                )

                if not previous_step_completed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"You must complete step {previous_step} before proceeding to step {step_data.step}",
                    )
            elif step_data.step > 1:
                # No onboarding data exists, but trying to skip step 1
                raise HTTPException(
                    status_code=400,
                    detail="You must start with step 1 of the onboarding process",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking previous step completion: {str(e)}")
            # Continue with the request if we can't check (don't block user completely)

    # Validate step-specific data only
    if step_data.step == 1:
        # Step 1: Only podcasting experience
        required_fields = ["podcasting_experience"]
        for field in required_fields:
            if not step_data.data.get(field):
                raise HTTPException(
                    status_code=400, detail=f"{field} is required for step 1"
                )

        # Validate podcasting experience value
        valid_experiences = ["0-1_year", "1-3_years", "3_years_plus"]
        if step_data.data.get("podcasting_experience") not in valid_experiences:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid podcasting experience. Must be one of: {', '.join(valid_experiences)}",
            )

    elif step_data.step == 2:
        # Step 2: Categories and network info
        if not step_data.data.get("category_ids"):
            raise HTTPException(
                status_code=400, detail="category_ids are required for step 2"
            )
        if not isinstance(step_data.data.get("category_ids"), list):
            raise HTTPException(status_code=400, detail="category_ids must be an array")
        if "is_part_of_network" not in step_data.data:
            raise HTTPException(
                status_code=400, detail="is_part_of_network is required for step 2"
            )

    elif step_data.step == 3:
        # Step 3: Location only
        if not step_data.data.get("location_id"):
            raise HTTPException(
                status_code=400, detail="location_id is required for step 3"
            )

    elif step_data.step == 4:
        # Step 4: Guest preferences
        required_fields = ["looking_for_guests", "wants_to_be_guest"]
        for field in required_fields:
            if field not in step_data.data:
                raise HTTPException(
                    status_code=400, detail=f"{field} is required for step 4"
                )

    elif step_data.step == 5:
        # Step 5: Favorite podcasts (final step)
        if "favorite_podcast_ids" not in step_data.data:
            raise HTTPException(
                status_code=400, detail="favorite_podcast_ids is required for step 5"
            )
        if not isinstance(step_data.data.get("favorite_podcast_ids"), list):
            raise HTTPException(status_code=400, detail="favorite_podcast_ids must be an array")
        
        # Note: Podcast metadata is fetched dynamically from podcasts table via JOINs
        # No need for denormalization as user_favorite_podcasts table is deprecated
    
    try:
        # Pass automatic favorites only for step 5
        auto_favorites = AUTOMATIC_FAVORITE_PODCASTS if step_data.step == 5 else None
        result = supabase_client.save_onboarding_step(user_id, step_data.step, step_data.data, user_token=None, automatic_favorites=auto_favorites)

        if result["success"]:
            # Track onboarding progress in Customer.io
            try:
                # Get user email for Customer.io
                user_data = supabase_client.service_client.auth.admin.get_user_by_id(user_id)
                user_email = user_data.user.email if user_data and user_data.user else None

                if user_email:
                    environment = os.getenv("ENVIRONMENT", "dev")

                    # Step 1: Mark onboarding as started
                    if step_data.step == 1:
                        customerio_result = customerio_client.update_user_attributes(
                            user_id=user_id,
                            email=user_email,
                            attributes={
                                "onboarding": "started",
                                "onboarding_environment": environment
                            }
                        )
                        if customerio_result["success"]:
                            logger.info(f"Customer.io: Marked onboarding as started for {user_email}")
                        else:
                            logger.warning(f"Customer.io: Failed to mark onboarding started: {customerio_result.get('error')}")

                    # Step 5: Mark onboarding as completed
                    elif step_data.step == 5:
                        customerio_result = customerio_client.update_user_attributes(
                            user_id=user_id,
                            email=user_email,
                            attributes={
                                "onboarding": "completed"
                            }
                        )
                        if customerio_result["success"]:
                            logger.info(f"Customer.io: Marked onboarding as completed for {user_email}")
                        else:
                            logger.warning(f"Customer.io: Failed to mark onboarding completed: {customerio_result.get('error')}")
            except Exception as e:
                # Don't fail the request if Customer.io tracking fails
                logger.warning(f"Customer.io onboarding tracking error (non-fatal): {str(e)}")

            # Invalidate episode cache for auto-favorite podcasts on step 5 completion
            if step_data.step == 5 and auto_favorites:
                for podcast in auto_favorites:
                    podcast_id = podcast.get("podcast_id")
                    if podcast_id:
                        podcast_service.episode_cache.invalidate_podcast(podcast_id)
                        logger.info(f"Invalidated episode cache for auto-favorite podcast {podcast_id} on user signup completion")

            step_name = {
                1: "podcasting experience",
                2: "categories and network info",
                3: "location selection",
                4: "guest preferences",
                5: "favorite podcasts",
            }.get(step_data.step, f"step {step_data.step}")

            completion_msg = " Onboarding completed!" if step_data.step == 5 else ""

            return OnboardingResponse(
                success=True,
                message=f"Step {step_data.step} ({step_name}) saved successfully.{completion_msg}",
            )
        else:
            error_msg = result.get("error", "Failed to save step data")
            raise HTTPException(status_code=500, detail=f"Save failed: {error_msg}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save onboarding step error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/user/favorite-podcasts", tags=["User"])
@limiter.limit("30/minute")
async def get_user_favorite_podcasts(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get user's favorite podcasts with most recent episode info"""
    try:
        favorite_podcasts = await podcast_service.get_user_favorite_podcasts(user_id)

        return {
            "success": True,
            "data": favorite_podcasts,
            "total": len(favorite_podcasts),
        }

    except Exception as e:
        logger.error(f"Error getting favorite podcasts: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Posts and Social Features Endpoints


@app.post("/api/v1/posts/upload-media", response_model=dict, tags=["Posts"])
@limiter.limit("20/minute")  # Higher limit for media uploads
async def upload_media(
    request: Request,
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_from_session),
):
    """Upload media files for posts (images, videos, audio)"""
    try:
        media_service = MediaService()
        result = await media_service.upload_media_files(files, user_id)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Media upload failed")


@app.post("/api/v1/posts", response_model=dict, tags=["Posts"])
@limiter.limit("10/minute")
async def create_post(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Create a new post

    Supports two modes:
    1. JSON mode (Content-Type: application/json):
       Send CreatePostRequest body with content and optional media_urls (pre-uploaded)

    2. Form-data mode (Content-Type: multipart/form-data):
       - content: Optional text content
       - post_type: Optional ("text", "image", "video", "audio")
       - podcast_episode_url: Optional
       - media_urls_json: Optional JSON string of pre-uploaded media URLs
       - files: Optional file uploads (up to 10 files)

    Both modes support any combination of content, images, and media.
    At least one of content, media_urls, or files must be provided.
    """
    try:
        import json

        media_urls = []
        content_type = request.headers.get("content-type", "")

        # Handle JSON mode (application/json)
        if "application/json" in content_type:
            body = await request.json()
            post_data = CreatePostRequest(**body)

            # For JSON mode, media is pre-uploaded, so fetch storage_path from temp_media_uploads
            media_items = []
            if post_data.media_urls:
                try:
                    # Query temp_media_uploads to get storage_path for each URL
                    result = (
                        supabase_client.service_client.table("temp_media_uploads")
                        .select("file_url, storage_path, media_type")
                        .in_("file_url", post_data.media_urls)
                        .eq("user_id", user_id)
                        .execute()
                    )

                    if result.data:
                        # Build media_items with storage_path
                        for item in result.data:
                            media_items.append(
                                {
                                    "url": item["file_url"],
                                    "storage_path": item.get("storage_path"),
                                    "type": item.get("media_type", "image"),
                                }
                            )
                except Exception as e:
                    logger.warning(
                        f"Could not fetch storage_path for pre-uploaded media: {e}"
                    )
                    # Fallback: create media_items without storage_path
                    media_items = [
                        {"url": url, "storage_path": None, "type": "image"}
                        for url in post_data.media_urls
                    ]

            post_dict = {
                "content": post_data.content,
                "post_type": post_data.post_type,
                "media_urls": post_data.media_urls or [],
                "media_items": media_items,
                "podcast_episode_url": post_data.podcast_episode_url,
                "hashtags": post_data.hashtags or [],
            }

        # Handle Form-data mode (multipart/form-data)
        elif "multipart/form-data" in content_type:
            # Parse form data manually
            form = await request.form()
            content = form.get("content")
            post_type = form.get("post_type") or "text"
            podcast_episode_url = form.get("podcast_episode_url")
            media_urls_json = form.get("media_urls_json")
            files = form.getlist("files")
            # Parse pre-uploaded media URLs from JSON string if provided
            if media_urls_json:
                try:
                    media_urls = json.loads(media_urls_json)
                    if not isinstance(media_urls, list):
                        raise ValueError("media_urls_json must be a JSON array")
                except (json.JSONDecodeError, ValueError) as e:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid media_urls_json: {str(e)}"
                    )

            has_content = content and content.strip()
            has_files = files and len(files) > 0
            has_media_urls = len(media_urls) > 0

            if not has_content and not has_files and not has_media_urls:
                raise HTTPException(
                    status_code=400,
                    detail="Post must have at least one of: content, files, or media_urls",
                )

            # Validate file count if files provided (max 10 files per post)
            if has_files and len(files) > 10:
                raise HTTPException(
                    status_code=400, detail="Maximum 10 files allowed per post"
                )

            # Upload new media files to R2 if provided
            uploaded_media_items = []
            if has_files:
                media_service = MediaService()
                # Upload all files at once
                upload_result = await media_service.upload_media_files(files, user_id)

                if upload_result["success"]:
                    # Store full media items (includes url, storage_path, type, etc.)
                    uploaded_media_items = upload_result["media"]
                    # Also extract URLs for backward compatibility
                    for media_item in upload_result["media"]:
                        media_urls.append(media_item["url"])
                else:
                    raise HTTPException(
                        status_code=500, detail="Failed to upload media files"
                    )

            # Determine post_type
            final_post_type = post_type or "text"
            if media_urls and final_post_type == "text":
                # Auto-detect post type based on first media file or URL
                if has_files and files and files[0].content_type:
                    if files[0].content_type.startswith("image/"):
                        final_post_type = "image"
                    elif files[0].content_type.startswith("video/"):
                        final_post_type = "video"
                    elif files[0].content_type.startswith("audio/"):
                        final_post_type = "audio"

            post_dict = {
                "content": content,
                "post_type": final_post_type,
                "media_urls": media_urls,
                "media_items": uploaded_media_items,  # Full media objects with storage_path
                "podcast_episode_url": podcast_episode_url,
                "hashtags": [],
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Type. Use application/json or multipart/form-data",
            )

        # Create the post
        result = await supabase_client.posts.create_post(user_id, post_dict)

        if result["success"]:
            # Mark media as used if post creation was successful
            if post_dict.get("media_urls"):
                media_service = MediaService()
                await media_service.mark_media_as_used(post_dict["media_urls"], user_id)

            # Invalidate feed cache after post creation
            get_feed_cache_service().invalidate()

            return {"success": True, "data": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create post error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/posts/feed", response_model=FeedResponse, tags=["Posts"])
@limiter.limit("30/minute")
async def get_feed(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    limit: int = Query(
        20, ge=1, le=100, description="Number of posts to return (1-100)"
    ),
    cursor: Optional[str] = Query(
        None, description="Cursor for pagination (created_at timestamp)"
    ),
    offset: Optional[int] = Query(
        None, ge=0, description="Offset for pagination (alternative to cursor)"
    ),
):
    """Get paginated feed of all posts

    Supports two pagination methods:
    1. Cursor-based (recommended): Use 'cursor' parameter with next_cursor from previous response
    2. Offset-based: Use 'offset' parameter for simple pagination
    """

    try:
        result = await supabase_client.posts.get_feed(user_id, limit, cursor, offset)

        if result["success"]:
            return result["data"]
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get feed error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/posts/my-posts", response_model=FeedResponse, tags=["Posts"])
@limiter.limit("60/minute")
async def get_my_posts(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get posts created by the current user"""

    try:
        result = supabase_client.posts.get_user_posts(user_id, user_id, limit, offset)

        if result["success"]:
            return FeedResponse(**result["data"])
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get my posts error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/posts/saved", response_model=dict, tags=["Posts"])
@limiter.limit("60/minute")
async def get_saved_posts(
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get posts saved by the current user"""

    try:
        result = supabase_client.posts.get_saved_posts(user_id, limit, cursor)

        if result["success"]:
            return {"success": True, "data": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get saved posts error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/posts/categories", response_model=dict, tags=["Posts"])
@limiter.limit("30/minute")
async def get_post_categories(request: Request):
    """Get all available post categories"""
    try:
        categories = await supabase_client.posts.get_available_categories()
        return {"success": True, "data": {"categories": categories}}

    except Exception as e:
        logger.error(f"Get post categories error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get post categories")


@app.get("/api/v1/posts/{post_id}", response_model=PostResponse, tags=["Posts"])
@limiter.limit("60/minute")
async def get_post(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get a single post"""

    try:
        result = supabase_client.posts.get_post(post_id, user_id)

        if result["success"]:
            post = result["data"]

            # Transform the response to match PostResponse model
            # The model expects 'user' but the method returns 'author'
            if "author" in post:
                # Fix the user object structure - change 'user_id' to 'id'
                if "user_id" in post["author"]:
                    post["author"]["id"] = post["author"]["user_id"]
                    del post["author"]["user_id"]

                post["user"] = post["author"]
                # Remove the author field to avoid duplication
                del post["author"]

            # Extract counts from engagement dict to top level
            if "engagement" in post:
                post["likes_count"] = post["engagement"].get("likes_count", 0)
                post["comments_count"] = post["engagement"].get("comments_count", 0)
                post["shares_count"] = post["engagement"].get("shares_count", 0)
                post["saves_count"] = post["engagement"].get("saves_count", 0)

            # Extract user engagement status to match model fields
            if "user_engagement" in post:
                post["is_liked"] = post["user_engagement"].get("liked", False)
                post["is_saved"] = post["user_engagement"].get("saved", False)
                post["is_shared"] = post["user_engagement"].get("shared", False)

            return post
        else:
            raise HTTPException(status_code=404, detail="Post not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get post error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/api/v1/posts/{post_id}", response_model=dict, tags=["Posts"])
@limiter.limit("10/minute")
async def update_post(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session)
):
    """Update a post

    Supports two modes:
    1. JSON mode (Content-Type: application/json):
       Send UpdatePostRequest body with optional content and media_urls (pre-uploaded)

    2. Form-data mode (Content-Type: multipart/form-data):
       - content: Optional text content (if provided, replaces existing content; empty string clears it)
       - post_type: Optional ("text", "image", "video", "audio")
       - podcast_episode_url: Optional
       - keep_media_ids: Optional JSON array of media IDs to keep (any existing media not in this list will be deleted)
       - media_urls_json: Optional JSON string of pre-uploaded media URLs to add
       - files: Optional file uploads to add (up to 10 files)

    Media handling:
    - If keep_media_ids is not provided: existing media is unchanged
    - If keep_media_ids is provided: only media IDs in the list are kept, others are deleted
    - New files are always added to remaining media

    At least one field must be provided to update.
    """
    try:
        import json

        content_type = request.headers.get("content-type", "")
        logger.info(f"[POST EDIT] post_id={post_id}, user_id={user_id}, content_type={content_type}")

        # Handle JSON mode (application/json)
        if "application/json" in content_type:
            body = await request.json()
            logger.info(f"[POST EDIT - JSON MODE] Raw body from client: {json.dumps(body, indent=2)}")
            update_data = UpdatePostRequest(**body)

            update_dict = {}
            if update_data.content is not None:
                update_dict["content"] = update_data.content
            if update_data.post_type is not None:
                update_dict["post_type"] = update_data.post_type
            if update_data.podcast_episode_url is not None:
                update_dict["podcast_episode_url"] = update_data.podcast_episode_url
            if update_data.media_urls is not None:
                update_dict["media_urls"] = update_data.media_urls

                # For JSON mode, media is pre-uploaded, fetch storage_path from temp_media_uploads
                media_items = []
                if update_data.media_urls:
                    try:
                        result = supabase_client.service_client.table('temp_media_uploads') \
                            .select('file_url, storage_path, media_type') \
                            .in_('file_url', update_data.media_urls) \
                            .eq('user_id', user_id) \
                            .execute()

                        if result.data:
                            for item in result.data:
                                media_items.append({
                                    'url': item['file_url'],
                                    'storage_path': item.get('storage_path'),
                                    'type': item.get('media_type', 'image')
                                })
                    except Exception as e:
                        logger.warning(f"Could not fetch storage_path for pre-uploaded media: {e}")
                        media_items = [{'url': url, 'storage_path': None, 'type': 'image'} for url in update_data.media_urls]

                update_dict["media_items"] = media_items

        # Handle Form-data mode (multipart/form-data)
        elif "multipart/form-data" in content_type:
            form = await request.form()
            content = form.get("content")
            post_type = form.get("post_type")
            podcast_episode_url = form.get("podcast_episode_url")
            keep_media_ids_json = form.get("keep_media_ids")
            media_urls_json = form.get("media_urls_json")
            files = form.getlist("files")

            # Log raw form data from client
            logger.info(f"[POST EDIT - FORM DATA MODE] Raw form data from client:")
            logger.info(f"  - content: {content}")
            logger.info(f"  - post_type: {post_type}")
            logger.info(f"  - podcast_episode_url: {podcast_episode_url}")
            logger.info(f"  - keep_media_ids_json: {keep_media_ids_json}")
            logger.info(f"  - media_urls_json: {media_urls_json}")
            logger.info(f"  - files count: {len(files) if files else 0}")
            if files:
                for i, file in enumerate(files):
                    logger.info(f"    - file[{i}]: filename={file.filename}, content_type={file.content_type}, size={file.size if hasattr(file, 'size') else 'unknown'}")

            update_dict = {}
            media_urls = []

            # Add text content if provided (even empty string to clear content)
            if content is not None:
                update_dict["content"] = content

            # Add post_type if provided
            if post_type is not None:
                update_dict["post_type"] = post_type

            # Add podcast_episode_url if provided
            if podcast_episode_url is not None:
                update_dict["podcast_episode_url"] = podcast_episode_url

            # Parse keep_media_ids from JSON string if provided
            if keep_media_ids_json:
                try:
                    keep_media_ids = json.loads(keep_media_ids_json)
                    if not isinstance(keep_media_ids, list):
                        raise ValueError("keep_media_ids must be a JSON array")
                    update_dict["keep_media_ids"] = keep_media_ids
                except (json.JSONDecodeError, ValueError) as e:
                    raise HTTPException(status_code=400, detail=f"Invalid keep_media_ids: {str(e)}")

            # Parse pre-uploaded media URLs from JSON string if provided
            if media_urls_json:
                try:
                    media_urls = json.loads(media_urls_json)
                    if not isinstance(media_urls, list):
                        raise ValueError("media_urls_json must be a JSON array")
                except (json.JSONDecodeError, ValueError) as e:
                    raise HTTPException(status_code=400, detail=f"Invalid media_urls_json: {str(e)}")

            # Validate file count if files provided (max 10 files per post)
            has_files = files and len(files) > 0
            if has_files and len(files) > 10:
                raise HTTPException(status_code=400, detail="Maximum 10 files allowed per post")

            # Upload new media files to R2 if provided
            uploaded_media_items = []
            if has_files:
                media_service = MediaService()
                upload_result = await media_service.upload_media_files(files, user_id)

                if upload_result["success"]:
                    uploaded_media_items = upload_result["media"]
                    for media_item in upload_result["media"]:
                        media_urls.append(media_item["url"])
                else:
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to upload media files"
                    )

            # Add media_urls and media_items if any media was provided
            if media_urls or uploaded_media_items:
                update_dict["media_urls"] = media_urls
                update_dict["media_items"] = uploaded_media_items

            # Validate at least one field is being updated
            if not update_dict:
                raise HTTPException(
                    status_code=400,
                    detail="At least one field must be provided to update"
                )

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Type. Use application/json or multipart/form-data"
            )

        # Validate at least one field is being updated
        if not update_dict:
            raise HTTPException(
                status_code=400,
                detail="At least one field must be provided to update"
            )

        # Log final processed update_dict before sending to update function
        logger.info(f"[POST EDIT] Final update_dict being sent to update function:")
        # Create a safe copy for logging (avoid logging large file data)
        safe_update_dict = update_dict.copy()
        if "media_items" in safe_update_dict and safe_update_dict["media_items"]:
            safe_update_dict["media_items"] = f"[{len(safe_update_dict['media_items'])} media items]"
        logger.info(f"  {json.dumps(safe_update_dict, indent=2)}")

        # Update the post
        result = supabase_client.posts.update_post(post_id, user_id, update_dict)

        logger.info(f"[POST EDIT] Update result - success: {result.get('success')}")
        if result.get("success"):
            logger.info(f"[POST EDIT] Updated post data: {json.dumps(result.get('data', {}), indent=2, default=str)}")
        else:
            logger.error(f"[POST EDIT] Update failed with error: {result.get('error')}")

        if result["success"]:
            # Mark media as used if media was updated
            if update_dict.get("media_urls"):
                media_service = MediaService()
                await media_service.mark_media_as_used(update_dict["media_urls"], user_id)

            # Invalidate feed cache after post update
            get_feed_cache_service().invalidate()

            return {"success": True, "data": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update post error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/v1/posts/{post_id}", response_model=dict, tags=["Posts"])
@limiter.limit("10/minute")
async def delete_post(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Delete a post"""

    try:
        result = supabase_client.posts.delete_post(post_id, user_id)

        if result["success"]:
            return {"success": True}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete post error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Post Interactions
@app.post(
    "/api/v1/posts/{post_id}/like", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("60/minute")
async def toggle_like(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Like or unlike a post"""

    try:
        result = supabase_client.posts.toggle_like(post_id, user_id)

        if result["success"]:
            # Send notification if post was liked (not unliked)
            if result["liked"]:
                try:
                    # Get post details to find the author
                    post = supabase_client.posts.get_post(post_id, user_id)
                    if post and post.get("author", {}).get("user_id"):
                        post_author_id = post["author"]["user_id"]

                        # Get liker's name
                        user_profile_service = UserProfileService()
                        liker_profile = await user_profile_service.get_user_profile(
                            user_id
                        )
                        liker_name = liker_profile.get("name", "Someone")

                        # Create notification
                        notification_service = NotificationService()
                        await notification_service.notify_post_like(
                            post_author_id=post_author_id,
                            liker_id=user_id,
                            liker_name=liker_name,
                            post_id=post_id,
                        )

                        # Send email notification for post owner (background task)
                        try:
                            from background_tasks import send_activity_notification_email
                            from email_notification_service import NOTIFICATION_TYPE_POST_REACTION

                            # Don't notify if user is liking their own post (already checked above, but explicit)
                            if post_author_id != user_id:
                                # Send email immediately as background task (non-blocking)
                                asyncio.create_task(send_activity_notification_email(
                                    user_id=post_author_id,
                                    notification_type=NOTIFICATION_TYPE_POST_REACTION,
                                    actor_id=user_id,
                                    resource_id=post_id
                                ))
                        except Exception as email_error:
                            logger.warning(f"Failed to send post reaction email notification: {email_error}")

                except Exception as e:
                    logger.warning(f"Failed to send post like notification: {e}")

            # Invalidate feed cache after post like/unlike
            get_feed_cache_service().invalidate()

            return {"success": True, "liked": result["liked"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Toggle like error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/posts/{post_id}/save", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("60/minute")
async def toggle_save(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Save or unsave a post"""

    try:
        result = supabase_client.posts.toggle_save(post_id, user_id)

        if result["success"]:
            return {"success": True, "saved": result["saved"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Toggle save error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/posts/{post_id}/comment", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("30/minute")
async def add_comment(
    post_id: str,
    comment_data: CreateCommentRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Add a comment to a post"""

    try:
        result = supabase_client.posts.add_comment(
            post_id, user_id, comment_data.content, comment_data.parent_comment_id
        )

        if result["success"]:
            # Send notification to post author
            try:
                # Get post details to find the author
                post = supabase_client.posts.get_post(post_id, user_id)
                if post and post.get("author", {}).get("user_id"):
                    post_author_id = post["author"]["user_id"]

                    # Get commenter's name
                    user_profile_service = UserProfileService()
                    commenter_profile = await user_profile_service.get_user_profile(
                        user_id
                    )
                    commenter_name = commenter_profile.get("name", "Someone")

                    # Create notification
                    notification_service = NotificationService()
                    await notification_service.notify_post_comment(
                        post_author_id=post_author_id,
                        commenter_id=user_id,
                        commenter_name=commenter_name,
                        post_id=post_id,
                        comment_preview=comment_data.content,
                    )
            except Exception as e:
                logger.warning(f"Failed to send comment notification: {e}")

            # Invalidate feed cache after comment addition
            get_feed_cache_service().invalidate()

            return {"success": True, "data": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add comment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/posts/{post_id}/comments", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("60/minute")
async def get_comments(
    post_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    limit: int = 20,
    cursor: Optional[str] = None,
):
    """Get comments for a post"""

    try:
        result = supabase_client.posts.get_comments(post_id, user_id, limit, cursor)

        if result["success"]:
            return result["data"]
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get comments error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put(
    "/api/v1/comments/{comment_id}", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("60/minute")
async def edit_comment(
    comment_id: str,
    comment_data: EditCommentRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Edit a comment"""

    try:
        result = supabase_client.posts.edit_comment(
            comment_id, user_id, comment_data.content
        )

        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Edit comment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete(
    "/api/v1/comments/{comment_id}", response_model=dict, tags=["Post Interactions"]
)
@limiter.limit("60/minute")
async def delete_comment(
    comment_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Delete a comment"""

    try:
        result = supabase_client.posts.delete_comment(comment_id, user_id)

        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete comment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post(
    "/api/v1/comments/{comment_id}/like",
    response_model=dict,
    tags=["Post Interactions"],
)
@limiter.limit("60/minute")
async def toggle_comment_like(
    comment_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Like or unlike a comment"""

    try:
        result = supabase_client.posts.toggle_comment_like(comment_id, user_id)

        if result["success"]:
            # Send notification if comment was liked (not unliked)
            if result["liked"]:
                try:
                    # Get comment details to find the author and post
                    comment_result = (
                        supabase_client.service_client.table("comments")
                        .select("user_id, post_id")
                        .eq("id", comment_id)
                        .single()
                        .execute()
                    )

                    if comment_result.data:
                        comment_author_id = comment_result.data.get("user_id")
                        post_id = comment_result.data.get("post_id")

                        # Get liker's name
                        user_profile_service = UserProfileService()
                        liker_profile = await user_profile_service.get_user_profile(
                            user_id
                        )
                        liker_name = liker_profile.get("name", "Someone")

                        # Create notification
                        notification_service = NotificationService()
                        await notification_service.notify_comment_like(
                            comment_author_id=comment_author_id,
                            liker_id=user_id,
                            liker_name=liker_name,
                            comment_id=comment_id,
                            post_id=post_id,
                        )
                except Exception as e:
                    logger.warning(f"Failed to send comment like notification: {e}")

            # Invalidate feed cache after comment like/unlike
            get_feed_cache_service().invalidate()

            return {"success": True, "liked": result["liked"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Toggle comment like error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/users/{target_user_id}/posts", response_model=FeedResponse, tags=["Posts"]
)
@limiter.limit("60/minute")
async def get_user_posts(
    target_user_id: str,
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get public posts from a specific user"""

    try:
        # Resolve "me" to actual user ID
        if target_user_id == "me":
            target_user_id = user_id

        result = supabase_client.posts.get_user_posts(user_id, target_user_id, limit, cursor)
        
        if result["success"]:
            return FeedResponse(**result["data"])
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user posts error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Network/Connections
@app.post("/api/v1/network/connect", response_model=dict, tags=["Network"])
@limiter.limit("30/minute")
async def send_connection_request(
    connection_data: ConnectionActionRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Send or manage connection request"""

    try:
        if connection_data.action == "connect":
            result = supabase_client.posts.send_connection_request(
                user_id, connection_data.user_id
            )

            # Invalidate profile cache for both users and send notification
            if result["success"]:
                # Invalidate profile cache
                try:
                    from user_profile_cache_service import get_user_profile_cache_service
                    profile_cache = get_user_profile_cache_service()
                    profile_cache.invalidate(user_id)
                    profile_cache.invalidate(connection_data.user_id)
                    logger.info(f"Invalidated profile cache for users {user_id} and {connection_data.user_id} after connection request")
                except Exception as e:
                    logger.warning(f"Failed to invalidate profile cache after connection request (non-fatal): {e}")

                # Send notification
                try:
                    user_profile_service = UserProfileService()
                    requester_profile = await user_profile_service.get_user_profile(
                        user_id
                    )
                    requester_name = requester_profile.get("name", "Someone")

                    notification_service = NotificationService()
                    await notification_service.notify_connection_request(
                        recipient_id=connection_data.user_id,
                        requester_id=user_id,
                        requester_name=requester_name,
                    )

                    # Send email notification for connection request (background task)
                    try:
                        from background_tasks import send_activity_notification_email
                        from email_notification_service import NOTIFICATION_TYPE_CONNECTION_REQUEST

                        # Send email immediately as background task (non-blocking)
                        asyncio.create_task(send_activity_notification_email(
                            user_id=connection_data.user_id,
                            notification_type=NOTIFICATION_TYPE_CONNECTION_REQUEST,
                            actor_id=user_id,
                            resource_id=None  # No specific resource for connection requests
                        ))
                    except Exception as email_error:
                        logger.warning(f"Failed to send connection request email notification: {email_error}")

                except Exception as e:
                    logger.warning(
                        f"Failed to send connection request notification: {e}"
                    )

        elif connection_data.action == "accept":
            # Find the connection request to accept
            connection_result = (
                supabase_client.service_client.table("user_connections")
                .select("*")
                .eq("follower_id", connection_data.user_id)
                .eq("following_id", user_id)
                .eq("status", "pending")
                .single()
                .execute()
            )

            if connection_result.data:
                result = supabase_client.posts.accept_connection(
                    connection_result.data["id"], user_id
                )

                # Invalidate profile cache for both users and send notification
                if result["success"]:
                    # Invalidate profile cache
                    try:
                        from user_profile_cache_service import get_user_profile_cache_service
                        profile_cache = get_user_profile_cache_service()
                        profile_cache.invalidate(user_id)
                        profile_cache.invalidate(connection_data.user_id)
                        logger.info(f"Invalidated profile cache for users {user_id} and {connection_data.user_id} after connection accepted")
                    except Exception as e:
                        logger.warning(f"Failed to invalidate profile cache after connection accept (non-fatal): {e}")

                    # Send notification
                    try:
                        user_profile_service = UserProfileService()
                        accepter_profile = await user_profile_service.get_user_profile(
                            user_id
                        )
                        accepter_name = accepter_profile.get("name", "Someone")

                        notification_service = NotificationService()
                        await notification_service.notify_connection_accepted(
                            requester_id=connection_data.user_id,
                            accepter_id=user_id,
                            accepter_name=accepter_name,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to send connection accepted notification: {e}"
                        )
            else:
                result = {"success": False, "error": "Connection request not found"}
        else:
            raise HTTPException(status_code=400, detail="Unsupported action")

        if result["success"]:
            return {"success": True}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Connection action error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/network/connections",
    response_model=ConnectionListResponse,
    tags=["Network"],
)
@limiter.limit("30/minute")
async def get_connections(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    status: str = "accepted",
    limit: int = 20,
    cursor: Optional[str] = None,
):
    """Get user connections"""

    try:
        result = supabase_client.posts.get_connections(user_id, status, limit, cursor)

        if result["success"]:
            return {
                "connections": result["data"]["connections"],
                "total_count": len(result["data"]["connections"]),
                "next_cursor": result["data"]["next_cursor"],
                "has_more": result["data"]["has_more"],
            }
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get connections error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/posts/feed/category/{category_id}", response_model=dict, tags=["Posts"]
)
@limiter.limit("60/minute")
async def get_feed_by_category(
    category_id: str,
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get feed posts filtered by AI-assigned category"""
    try:
        result = supabase_client.posts.get_feed_by_category(
            user_id, category_id, limit, cursor
        )

        if result["success"]:
            return {"success": True, "data": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get feed by category error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/discovery/creators", response_model=dict, tags=["Discovery"])
@limiter.limit("20/minute")
async def get_suggested_creators(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get 5 random creators to follow"""

    try:
        # Get users who have connections (active users) to suggest
        # Query user_connections to find users who have followers/following
        connections_result = (
            supabase_client.service_client.table("user_connections")
            .select("follower_id, following_id")
            .neq("follower_id", user_id)
            .neq("following_id", user_id)
            .limit(100)
            .execute()
        )

        if not connections_result.data:
            return {"suggested_creators": []}

        # Extract unique user IDs from connections
        user_ids = set()
        for conn in connections_result.data:
            user_ids.add(conn["follower_id"])
            user_ids.add(conn["following_id"])

        # Convert to list and get up to 50 random user IDs
        import random

        user_ids_list = list(user_ids)
        if len(user_ids_list) > 50:
            user_ids_list = random.sample(user_ids_list, 50)

        # Get user profiles using UserProfileService (includes avatars with signed URLs)
        from user_profile_service import UserProfileService
        profile_service = UserProfileService()
        user_profiles = await profile_service.get_users_by_ids(user_ids_list)

        # Format creators for response
        suggested_creators = []
        for profile in user_profiles:
            creator = {
                "id": profile["id"],
                "full_name": profile.get("name", "Unknown"),
                "username": profile.get("email", "").split("@")[0] if profile.get("email") else "unknown",
                "bio": profile.get("bio", ""),
                "profile_picture_url": profile.get("avatar_url"),  # Now includes signed URL
                "created_at": profile.get("created_at"),
            }
            suggested_creators.append(creator)

        # Select 5 random creators from the results
        random_creators = random.sample(
            suggested_creators, min(5, len(suggested_creators))
        )

        return {"suggested_creators": random_creators}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get suggested creators error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/creators", response_model=dict, tags=["Creators"])
@limiter.limit("30/minute")
async def get_all_creators(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
):
    """Get all creators with pagination"""

    try:
        # Get active users who have connections (indicating they're active creators)
        connections_query = (
            supabase_client.service_client.table("user_connections")
            .select("follower_id, following_id")
            .limit(1000)
        )  # Get a large sample of connections

        connections_result = connections_query.execute()

        if not connections_result.data:
            return {"creators": [], "total_count": 0, "has_more": False}

        # Extract unique user IDs from connections
        user_ids = set()
        for conn in connections_result.data:
            user_ids.add(conn["follower_id"])
            user_ids.add(conn["following_id"])

        # Remove current user from results
        user_ids.discard(user_id)

        # Convert to sorted list for consistent pagination
        user_ids_list = sorted(list(user_ids))

        # Apply search filter if provided
        if search:
            filtered_creators = []
            search_lower = search.lower()

            # Get user data for all users to enable search
            for uid in user_ids_list:
                try:
                    user_response = (
                        supabase_client.service_client.auth.admin.get_user_by_id(uid)
                    )
                    if user_response and user_response.user:
                        user = user_response.user
                        user_metadata = user.user_metadata or {}

                        # Get username first as fallback
                        username = user_metadata.get("username") or (
                            user.email.split("@")[0] if user.email else "unknown"
                        )
                        full_name = (
                            user_metadata.get("name")
                            or user_metadata.get("full_name")
                            or username
                        )
                        bio = user_metadata.get("bio") or ""

                        # Check if search term matches name, username, or bio
                        if (
                            search_lower in full_name.lower()
                            or search_lower in username.lower()
                            or search_lower in bio.lower()
                        ):
                            creator = {
                                "id": user.id,
                                "full_name": full_name,
                                "username": username,
                                "bio": bio,
                                "profile_picture_url": user_metadata.get(
                                    "profile_picture_url"
                                ),
                                "created_at": user.created_at,
                            }
                            filtered_creators.append(creator)
                except Exception:
                    continue

            # Apply pagination to filtered results
            total_count = len(filtered_creators)
            paginated_creators = filtered_creators[offset : offset + limit]
            has_more = offset + limit < total_count

        else:
            # Apply pagination to user IDs first, then fetch user data
            total_count = len(user_ids_list)
            paginated_user_ids = user_ids_list[offset : offset + limit]
            has_more = offset + limit < total_count

            # Get user data for paginated user IDs
            paginated_creators = []
            for uid in paginated_user_ids:
                try:
                    user_response = (
                        supabase_client.service_client.auth.admin.get_user_by_id(uid)
                    )
                    if user_response and user_response.user:
                        user = user_response.user
                        user_metadata = user.user_metadata or {}

                        # Get username first as fallback
                        username = user_metadata.get("username") or (
                            user.email.split("@")[0] if user.email else "unknown"
                        )

                        creator = {
                            "id": user.id,
                            "full_name": user_metadata.get("name")
                            or user_metadata.get("full_name")
                            or username,
                            "username": username,
                            "bio": user_metadata.get("bio", ""),
                            "profile_picture_url": user_metadata.get(
                                "profile_picture_url"
                            ),
                            "created_at": user.created_at,
                        }
                        paginated_creators.append(creator)
                except Exception:
                    # Skip users that can't be fetched
                    continue

        return {
            "creators": paginated_creators,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get all creators error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/network/connection-requests",
    response_model=ConnectionListResponse,
    tags=["Network"],
)
@limiter.limit("30/minute")
async def get_connection_requests(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    limit: int = 20,
    cursor: Optional[str] = None,
):
    """Get pending connection requests"""

    try:
        result = supabase_client.posts.get_connections(
            user_id, status="pending", limit=limit, cursor=cursor
        )

        if result["success"]:
            return {
                "connections": result["data"]["connections"],
                "total_count": len(result["data"]["connections"]),
                "next_cursor": result["data"]["next_cursor"],
                "has_more": result["data"]["has_more"],
            }
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get connection requests error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# @app.get("/api/v1/discover/topics", response_model=TopicsResponse, tags=["Discovery"])
@limiter.limit("20/minute")
async def get_trending_topics(request: Request, limit: int = 20):
    """Get trending topics/hashtags"""

    try:
        # For MVP, return static trending topics
        # Future: Implement algorithm based on recent post activity
        trending_topics = [
            {"name": "podcasting", "post_count": 1250, "trending_score": 95},
            {"name": "audio", "post_count": 890, "trending_score": 87},
            {"name": "storytelling", "post_count": 670, "trending_score": 82},
            {"name": "interviews", "post_count": 540, "trending_score": 78},
            {"name": "business", "post_count": 480, "trending_score": 73},
            {"name": "marketing", "post_count": 420, "trending_score": 69},
            {"name": "creativity", "post_count": 380, "trending_score": 65},
            {"name": "technology", "post_count": 340, "trending_score": 61},
            {"name": "education", "post_count": 310, "trending_score": 58},
            {"name": "entertainment", "post_count": 280, "trending_score": 54},
        ]

        return {"trending_topics": trending_topics[:limit]}

    except Exception as e:
        logger.error(f"Get trending topics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Resources Endpoints

@app.get("/api/v1/blogs/categories/all", response_model=List[ResourceCategoryResponse], tags=["Blogs"])
@limiter.limit("60/minute")
async def get_all_blog_categories(request: Request):
    """
    Get all available blog categories.
    """
    try:
        categories_data = await resources_service.get_resource_categories()
        return categories_data
    except Exception as e:
        logger.error(f"Failed to get blog categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve blog categories")

@app.get(
    "/api/v1/blogs/all",
    response_model=BlogsResponse,
    tags=["Blogs"],
    summary="Get all blog posts",
)
async def get_all_blog_posts(
    limit: int = 20,
    offset: int = 0,
):
    """
    Get all resources that are marked as blog posts.
    This is a public endpoint and does not require authentication.
    """
    try:
        # Service method to get blogs
        result = await resources_service.get_blog_posts(
            limit=limit, offset=offset
        )
        return result
    except Exception as e:
        logger.error(f"Failed to get blog posts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve blog posts")


@app.get(
    "/api/v1/blog/{blog_id}",
    tags=["Blogs"],
    summary="Get single blog post",
    response_model=BlogResponse
)
async def get_single_blog_post(blog_id:str)-> Dict[str, Any]:
    try:
        return await resources_service.get_blog(blog_id)
    except Exception as e:
        logger.error(f"Failed to get blog posts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve blog posts")


@app.get(
    "/api/v1/resources/blogs/category/{category_id}",
    response_model=BlogsResponse,
    tags=["Blogs"],
    summary="Get blog posts by category",
)
async def get_blogs_by_category(
    category_id: UUID, limit: int = 20, offset: int = 0
):
    """
    Get blog posts by category
    Public endpoint, no authentication required.
    """
    try:
        result = await resources_service.get_blog_posts_by_category(
            category_id=str(category_id), limit=limit, offset=offset
        )
        return result
    except Exception as e:
        logger.error(f"Error getting blogs by category: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get blog posts")



@app.get("/api/v1/resources", response_model=ResourcesResponse, tags=["Resources"])
@limiter.limit("20/minute")
async def get_resources(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    is_premium: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Get resources with premium access control - articles are free, some videos are premium-only"""
    try:
        result = await resources_service.get_resources(
            user_id=user_id,
            category=category,
            resource_type=resource_type,
            is_premium=is_premium,
            search=search,
            limit=limit,
            offset=offset,
        )
        return result

    except Exception as e:
        logger.error(f"Get resources error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get resources")


@app.get("/api/v1/resources/categories", tags=["Resources"])
@limiter.limit("20/minute")
async def get_resource_categories(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get all resource categories"""
    try:
        categories = await resources_service.get_resource_categories()
        return {"categories": categories}

    except Exception as e:
        logger.error(f"Get resource categories error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get resource categories")


@app.post(
    "/api/v1/resources", response_model=ResourceResponse, tags=["Resources", "Admin"]
)
@limiter.limit("5/minute")
async def create_resource(
    request: Request,
    resource_data: CreateResourceRequest,
    user_id: str = Depends(get_current_user_from_session),
):
    """Create a new resource (Admin only)"""
    try:
        # Check if user is admin (you may want to implement proper admin check)
        # For now, any authenticated user can create resources

        # Convert Pydantic model to dict
        resource_dict = resource_data.dict()

        # Create the resource
        result = await resources_service.create_resource(resource_dict)

        if result["success"]:
            return result["data"]
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create resource error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create resource")


@app.get("/api/v1/resources/{resource_id}", tags=["Resources"])
@limiter.limit("20/minute")
async def get_resource_by_id(
    request: Request,
    resource_id: str,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get single resource with premium access control"""
    try:
        resource = await resources_service.get_resource_by_id(user_id, resource_id)

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        return resource

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get resource {resource_id} error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get resource")


@app.get("/api/v1/resources/{resource_id}/content", tags=["Resources"])
@limiter.limit("20/minute")
async def get_article_content(
    request: Request,
    resource_id: str,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get article content from R2 storage"""
    try:
        result = await resources_service.get_article_content(user_id, resource_id)

        if not result["success"]:
            if result["error"] == "Resource not found":
                raise HTTPException(status_code=404, detail=result["error"])
            elif result["error"] == "Premium subscription required":
                raise HTTPException(status_code=403, detail=result["error"])
            else:
                raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get article content error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get article content")


@app.get("/api/v1/resources/{resource_id}/action-guide", tags=["Resources"])
@limiter.limit("10/minute")
async def get_resource_action_guide(
    request: Request,
    resource_id: str,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get action guide download URL for a resource"""
    try:
        # First check if user has access to the resource
        resource = await resources_service.get_resource_by_id(user_id, resource_id)

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        if not resource.get("user_has_access", False):
            raise HTTPException(status_code=403, detail="Premium subscription required")

        if resource.get("type") not in ["article", "guide"]:
            raise HTTPException(
                status_code=400,
                detail="Action guides are only available for articles and guides",
            )

        # Get action guide URL
        action_guide_url = resource.get("action_guide_url")
        if not action_guide_url:
            # Try to generate one
            from action_guide_service import action_guide_service

            action_guide_url = action_guide_service.generate_download_url(
                resource_id, resource.get("category", "general")
            )

        if not action_guide_url:
            raise HTTPException(
                status_code=404, detail="Action guide not available for this resource"
            )

        return {
            "success": True,
            "download_url": action_guide_url,
            "filename": f"{resource_id}_action_guide.pdf",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get action guide error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get action guide")


@app.post("/api/v1/resources/{resource_id}/pdf-guide", tags=["Resources", "Admin"])
@limiter.limit("5/minute")
async def upload_resource_pdf_guide(
    request: Request,
    resource_id: str,
    pdf_file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_from_session),
):
    """
    Upload a PDF guide for a resource (article or video)
    Admin only - requires proper authorization
    """
    try:
        # TODO: Add admin role check here
        # For now, we'll allow authenticated users to upload

        # Get the resource to verify it exists and get its type
        resource_result = await resources_service.get_resource_by_id(
            user_id, resource_id
        )

        if not resource_result:
            raise HTTPException(status_code=404, detail="Resource not found")

        resource_type = resource_result.get("type")
        if resource_type not in ["article", "video"]:
            raise HTTPException(
                status_code=400,
                detail="PDF guides can only be uploaded for articles and videos",
            )

        # Upload the PDF
        upload_result = await resource_pdf_service.upload_pdf_guide(
            resource_id=resource_id, resource_type=resource_type, pdf_file=pdf_file
        )

        if not upload_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=upload_result.get("error", "Failed to upload PDF"),
            )

        # Update the resource with the download URL
        update_result = resources_service.update_resource_download_url(
            resource_id=resource_id, download_url=upload_result["url"]
        )

        return {
            "success": True,
            "message": f"PDF guide uploaded successfully for {resource_type}",
            "url": upload_result["url"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload PDF guide error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload PDF guide")


@app.get("/api/v1/resources/{resource_id}/pdf-guide", tags=["Resources"])
@limiter.limit("10/minute")
async def get_resource_pdf_guide(
    request: Request,
    resource_id: str,
    user_id: str = Depends(get_current_user_from_session),
):
    """
    Get the download URL for a resource's PDF guide
    Available for articles and videos with accompanying guides
    """
    try:
        # First check if user has access to the resource
        resource = await resources_service.get_resource_by_id(user_id, resource_id)

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        if not resource.get("user_has_access", False):
            raise HTTPException(status_code=403, detail="Premium subscription required")

        resource_type = resource.get("type")
        if resource_type not in ["article", "video"]:
            raise HTTPException(
                status_code=400,
                detail="PDF guides are only available for articles and videos",
            )

        # Get PDF guide URL
        pdf_url = resource.get("download_url")
        if not pdf_url:
            # Try to generate a presigned URL
            pdf_url = resource_pdf_service.generate_download_url(
                resource_id, resource_type
            )

        if not pdf_url:
            raise HTTPException(
                status_code=404, detail="PDF guide not available for this resource"
            )

        return {
            "success": True,
            "download_url": pdf_url,
            "filename": f"{resource_id}_{resource_type}_guide.pdf",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get PDF guide error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get PDF guide")


# Experts Endpoints
@app.get("/api/v1/experts", tags=["Resources", "Experts"])
@limiter.limit("20/minute")
async def get_experts(
    request: Request,
    is_available: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Get experts for 'Connect with an Expert' feature"""
    try:
        result = await resources_service.get_experts(
            is_available=is_available, search=search, limit=limit, offset=offset
        )
        return result

    except Exception as e:
        logger.error(f"Get experts error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get experts")


@app.get("/api/v1/experts/{expert_id}", tags=["Resources", "Experts"])
@limiter.limit("20/minute")
async def get_expert_by_id(request: Request, expert_id: str):
    """Get single expert by ID"""
    try:
        expert = await resources_service.get_expert_by_id(expert_id)

        if not expert:
            raise HTTPException(status_code=404, detail="Expert not found")

        return expert

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get expert {expert_id} error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get expert")


# Partner Deals Endpoints
@app.get("/api/v1/partners/deals", tags=["Resources", "Partners"])
@limiter.limit("20/minute")
async def get_partner_deals(request: Request, limit: int = 20, offset: int = 0):
    """Get partner deals and offers"""
    try:
        result = await resources_service.get_partner_deals(limit=limit, offset=offset)
        return result

    except Exception as e:
        logger.error(f"Get partner deals error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get partner deals")


@app.get("/api/v1/partners/deals/{deal_id}", tags=["Resources", "Partners"])
@limiter.limit("20/minute")
async def get_partner_deal_by_id(request: Request, deal_id: str):
    """Get single partner deal by ID"""
    try:
        deal = await resources_service.get_partner_deal_by_id(deal_id)

        if not deal:
            raise HTTPException(
                status_code=404, detail="Partner deal not found or expired"
            )

        return deal

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get partner deal {deal_id} error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get partner deal")


# =============================================================================
# RESOURCE INTERACTION TRACKING ENDPOINTS
# =============================================================================

from pydantic import BaseModel


class InteractionRequest(BaseModel):
    interaction_data: Optional[Dict[str, Any]] = None


class ListeningProgressRequest(BaseModel):
    progress_seconds: int
    duration_seconds: Optional[int] = None
    playback_speed: float = 1.0


@app.post("/api/v1/resources/{resource_id}/interactions", tags=["Resources"])
async def track_resource_interaction(
    request: Request,
    resource_id: str,
    interaction_type: str,
    body: InteractionRequest = None,
    session_id: Optional[str] = None,
):
    """
    Track user interaction with a resource

    Interaction types:
    - article_opened: User opened an article
    - article_read_progress: User is reading (send periodically with scroll_percentage)
    - article_completed: User completed reading the article
    - guide_downloaded: User downloaded an action guide
    - video_started: User started playing a video
    - video_played: Video playback started/resumed
    - video_paused: Video playback paused
    - video_seeked: User seeked to different position
    - video_progress: Video progress update (send periodically with position and duration)
    - video_completed: User watched video to completion

    Example interaction_data for different types:
    - article_read_progress: {"scroll_percentage": 45, "read_time_delta": 30}
    - video_progress: {"position": 120, "duration": 300, "watch_time_delta": 5}
    - video_seeked: {"from_position": 60, "to_position": 120}
    """
    try:
        user_id = get_current_user_id(request)
        interaction_service = get_resource_interaction_service()

        result = await interaction_service.track_interaction(
            user_id=user_id,
            resource_id=resource_id,
            interaction_type=interaction_type,
            interaction_data=body.interaction_data if body else None,
            session_id=session_id,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking resource interaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to track interaction")


# @app.get("/api/v1/resources/{resource_id}/stats", tags=["Resources", "Analytics"])
# async def get_resource_stats(
#     request: Request,
#     resource_id: str
# ):
#     """Get user's statistics for a specific resource"""
#     try:
#         user_id = get_current_user_id(request)
#         interaction_service = get_resource_interaction_service()
#
#         stats = await interaction_service.get_user_resource_stats(user_id, resource_id)
#
#         if not stats:
#             return {"success": True, "data": None, "message": "No interaction data found"}
#
#         return {"success": True, "data": stats}
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting resource stats: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get resource stats")


@app.get("/api/v1/users/resources/progress", tags=["Resources"])
async def get_resources_progress(
    request: Request,
    is_completed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get all resources the user has interacted with and their progress

    Query parameters:
    - is_completed: Filter by completion status (true/false)
    - limit: Number of resources to return
    - offset: Pagination offset
    """
    try:
        user_id = get_current_user_id(request)
        interaction_service = get_resource_interaction_service()

        result = await interaction_service.get_user_resources_progress(
            user_id=user_id, is_completed=is_completed, limit=limit, offset=offset
        )

        return {"success": True, "data": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting resources progress: {e}")
        raise HTTPException(status_code=500, detail="Failed to get resources progress")


@app.get("/api/v1/discover/events", response_model=EventsResponse, tags=["Discovery"])
@limiter.limit("20/minute")
async def get_events(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get one random upcoming podcasting event"""

    try:
        # Return one random upcoming event
        from datetime import datetime, timedelta
        import random

        future_date = datetime.utcnow() + timedelta(days=30)

        # Pool of possible upcoming events
        all_events = [
            {
                "id": "1",
                "title": "PodcastCon 2024",
                "description": "The premier podcasting conference with industry leaders and networking opportunities.",
                "date": future_date.isoformat() + "Z",
                "location": "Austin, TX",
                "url": "https://example.com/podcastcon",
                "event_type": "conference",
                "is_online": False,
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "2",
                "title": "Audio Storytelling Workshop",
                "description": "Learn advanced storytelling techniques from award-winning podcast producers.",
                "date": (future_date + timedelta(days=7)).isoformat() + "Z",
                "location": "Online",
                "url": "https://example.com/workshop",
                "event_type": "workshop",
                "is_online": True,
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "id": "3",
                "title": "Podcast Monetization Summit",
                "description": "Master the art of podcast monetization with successful creators and industry experts.",
                "date": (future_date + timedelta(days=14)).isoformat() + "Z",
                "location": "Los Angeles, CA",
                "url": "https://example.com/monetization",
                "event_type": "summit",
                "is_online": False,
                "created_at": "2024-01-03T00:00:00Z",
            },
            {
                "id": "4",
                "title": "Voice Tech Meetup",
                "description": "Explore the latest in voice technology and audio innovation for podcasters.",
                "date": (future_date + timedelta(days=21)).isoformat() + "Z",
                "location": "Online",
                "url": "https://example.com/voicetech",
                "event_type": "meetup",
                "is_online": True,
                "created_at": "2024-01-04T00:00:00Z",
            },
        ]

        # Return one random event
        random_event = random.choice(all_events)
        return {"events": [random_event]}

    except Exception as e:
        logger.error(f"Get events error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/discover/resources", response_model=ResourcesResponse, tags=["Discovery"]
)
@limiter.limit("20/minute")
async def get_discover_resources(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get one random resource for discovery"""

    try:
        # Get one random resource from the resources service
        import random

        # Get a larger pool of resources to randomly select from
        result = await resources_service.get_resources(
            user_id=None,  # Don't filter by user for discovery
            category=None,
            resource_type=None,
            is_premium=False,  # Only include free resources for discovery
            search=None,
            limit=50,
            offset=0,
        )

        if not result.get("resources"):
            return {"resources": []}

        # Select one random resource
        random_resource = random.choice(result["resources"])
        return {"resources": [random_resource]}

    except Exception as e:
        logger.error(f"Get discover resources error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==========================================
# COMPREHENSIVE EVENTS SYSTEM ENDPOINTS
# ==========================================


@app.get("/api/v1/events", tags=["Events"])
@limiter.limit("30/minute")
async def get_events_list(
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
    event_type: str = "upcoming",  # upcoming, past, all
    category: Optional[str] = None,
    tags: Optional[str] = None,  # comma-separated
    is_paid: Optional[bool] = None,
    search: Optional[str] = None,
    host_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Get events with comprehensive filtering"""
    try:
        # Parse tags if provided
        tag_list = [tag.strip() for tag in tags.split(",")] if tags else None

        result = await events_service.get_events(
            user_id=user_id,
            event_type=event_type,
            category=category,
            tags=tag_list,
            is_paid=is_paid,
            search=search,
            host_id=host_id,
            limit=limit,
            offset=offset,
        )

        if result["success"]:
            return {
                "events": result["data"]["events"],
                "total_count": result["data"]["total_count"],
                "has_more": result["data"]["has_more"],
            }
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get events list error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get events")


@app.get("/api/v1/events/{event_id}", tags=["Events"])
@limiter.limit("30/minute")
async def get_event_detail(
    request: Request,
    event_id: str,
    user_id: str = Depends(get_current_user_from_session),
):
    """Get single event with full details"""
    try:
        result = await events_service.get_event_by_id(event_id, user_id)

        if result["success"]:
            return result["data"]
        else:
            if "not found" in result["error"].lower():
                raise HTTPException(status_code=404, detail=result["error"])
            else:
                raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event detail error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get event")


@app.post("/api/v1/events", tags=["Events"])
@limiter.limit("10/minute")
async def create_event(
    request: Request,
    event_data: dict,
    user_id: str = Depends(get_current_user_from_session),
):
    """Create a new event (admin only - all events are PodGround events)"""
    try:
        # TODO: Add admin access control check
        # For now, this endpoint would be admin-only in production
        result = await events_service.create_event(event_data)

        if result["success"]:
            return result["data"]
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create event error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create event")


# REMOVED ENDPOINTS:
# - POST /api/v1/events/{event_id}/register - Registration now handled via Calget
# - DELETE /api/v1/events/{event_id}/register - Cancellation now handled via Calget
# - GET /api/v1/events/{event_id}/attendees - Attendee management via Calget
# - GET /api/v1/events/{event_id}/calendar - Calendar integration via Calget
# - GET /api/v1/users/events - User registrations tracked via Calget


@app.get("/api/v1/events/tags", tags=["Events"])
@limiter.limit("20/minute")
async def get_event_tags(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get available event tags"""
    try:
        result = await events_service.get_event_tags()

        if result["success"]:
            return {"tags": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get event tags error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get event tags")


@app.post("/api/v1/events/{event_id}/image", tags=["Events"])
@limiter.limit("5/minute")
async def upload_event_image(
    request: Request,
    event_id: str,
    image: UploadFile,
    user_id: str = Depends(get_current_user_from_session),
):
    """Upload thumbnail image for an event (host only)"""
    try:
        # Check if event exists
        event_result = await events_service.get_event_by_id(event_id, user_id)
        if not event_result["success"]:
            raise HTTPException(status_code=404, detail="Event not found")

        # For now, any authenticated user can upload event images
        # In production, this would be admin-only
        event = event_result["data"]

        # Validate image file
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        # Upload image using media service
        from media_service import MediaService

        media_service = MediaService()

        upload_result = await media_service.upload_media_files([image], user_id)

        if not upload_result.get("success"):
            raise HTTPException(status_code=500, detail="Failed to upload image")

        # Get the uploaded image URL
        uploaded_media = upload_result.get("media", [])
        if not uploaded_media:
            raise HTTPException(status_code=500, detail="No image was uploaded")

        image_url = uploaded_media[0]["file_url"]

        # Update event with new image URL
        update_result = await events_service.update_event(
            event_id=event_id, update_data={"image_url": image_url}
        )

        if update_result["success"]:
            # Mark media as used so it doesn't get cleaned up
            media_urls = [image_url]
            thumbnail_url = uploaded_media[0].get("thumbnail_url")
            if thumbnail_url:
                media_urls.append(thumbnail_url)

            await media_service.mark_media_as_used(media_urls, user_id)

            return {
                "success": True,
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update event image")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload event image error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload event image")


# @app.post("/api/v1/events/{event_id}/feedback", tags=["Events"])
# @limiter.limit("5/minute")
# async def submit_event_feedback(
#     request: Request,
#     event_id: str,
#     feedback_data: dict,
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Submit feedback for an attended event"""
#     try:
#         result = await events_service.submit_event_feedback(
#             event_id=event_id,
#             user_id=user_id,
#             feedback_data=feedback_data
#         )
#
#         if result['success']:
#             return result['data']
#         else:
#             if 'only attendees' in result['error'].lower():
#                 raise HTTPException(status_code=403, detail=result['error'])
#             else:
#                 raise HTTPException(status_code=400, detail=result['error'])
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Submit feedback error: {str(e)}")
#         raise HTTPException(status_code=500, detail="Failed to submit feedback")


# Subscription Management Endpoints
@app.get(
    "/api/v1/subscriptions/plans",
    response_model=SubscriptionPlansResponse,
    tags=["Subscriptions"],
)
@limiter.limit("20/minute")
async def get_subscription_plans(request: Request):
    """Get available subscription plans"""

    try:
        result = supabase_client.get_subscription_plans()

        if result["success"]:
            return {"plans": result["data"]}
        else:
            raise HTTPException(status_code=500, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get subscription plans error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/api/v1/subscriptions/current",
    response_model=UserSubscriptionResponse,
    tags=["Subscriptions"],
)
@limiter.limit("30/minute")
async def get_current_subscription(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get user's current subscription"""

    try:
        result = supabase_client.get_user_subscription(user_id)

        if result["success"]:
            return {"subscription": result["data"]}
        else:
            raise HTTPException(status_code=404, detail="No subscription found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get current subscription error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/v1/subscriptions/create", response_model=dict, tags=["Subscriptions"])
@limiter.limit("10/minute")
async def create_subscription(
    subscription_data: CreateSubscriptionRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Create or update user subscription"""

    try:
        result = supabase_client.create_subscription(
            user_id=user_id,
            plan_name=subscription_data.plan_name,
            stripe_customer_id=subscription_data.stripe_customer_id,
            stripe_subscription_id=subscription_data.stripe_subscription_id,
        )

        if result["success"]:
            return {
                "success": True,
                "message": f"Subscription to {subscription_data.plan_name} plan created successfully",
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create subscription error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/api/v1/subscriptions/status", response_model=dict, tags=["Subscriptions"])
@limiter.limit("10/minute")
async def update_subscription_status(
    status_data: UpdateSubscriptionRequest,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Update subscription status"""

    try:
        result = supabase_client.update_subscription_status(user_id, status_data.status)

        if result["success"]:
            return {
                "success": True,
                "message": f"Subscription status updated to {status_data.status}",
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update subscription status error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Admin Endpoints
# @app.post("/api/v1/admin/assign-role", response_model=dict, tags=["Admin"])
# @limiter.limit("10/minute")
# @require_role("admin")
# async def assign_user_role(role_data: AssignRoleRequest, request: Request, _: None = Depends(require_localhost), user_id: str = Depends(get_current_user_from_session)):
#     """Assign role to a user (admin only)"""
#
#     try:
#         result = supabase_client.assign_user_role(
#             user_id=role_data.user_id,
#             role=role_data.role,
#             granted_by=user_id
#         )
#
#         if result["success"]:
#             return {"success": True, "message": f"Role {role_data.role} assigned to user {role_data.user_id}"}
#         else:
#             raise HTTPException(status_code=400, detail=result["error"])
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Assign role error: {str(e)}")
#         raise HTTPException(status_code=500, detail="Internal server error")

# @app.post("/api/v1/admin/fix-categories-schema", response_model=dict, tags=["Admin"])
# @limiter.limit("1/minute")
# async def fix_categories_schema(request: Request, _: None = Depends(require_localhost), user_id: str = Depends(get_current_user_from_session)):
#     """Fix user_onboarding_categories table schema to use UUID (temporary admin endpoint)"""
#
#     try:
#         # Execute the migration SQL via service client
#         if not supabase_client.service_client:
#             raise HTTPException(status_code=500, detail="Service client not available")
#
#         # Read migration SQL
#         migration_sql = """
#         -- Drop the table and recreate it with correct UUID types
#         DROP TABLE IF EXISTS public.user_onboarding_categories CASCADE;
#
#         -- Recreate the table with correct UUID structure
#         CREATE TABLE public.user_onboarding_categories (
#             id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#             user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
#             category_id UUID NOT NULL REFERENCES public.podcast_categories(id) ON DELETE CASCADE,
#             created_at TIMESTAMPTZ DEFAULT NOW(),
#
#             -- Ensure each user can only select a category once
#             UNIQUE(user_id, category_id)
#         );
#
#         -- Create indexes for performance
#         CREATE INDEX idx_user_onboarding_categories_user_id ON public.user_onboarding_categories(user_id);
#         CREATE INDEX idx_user_onboarding_categories_category_id ON public.user_onboarding_categories(category_id);
#
#         -- Enable RLS
#         ALTER TABLE public.user_onboarding_categories ENABLE ROW LEVEL SECURITY;
#
#         -- RLS Policies
#         CREATE POLICY "Category selections viewable by authenticated users" ON public.user_onboarding_categories
#             FOR SELECT
#             USING (auth.uid() IS NOT NULL);
#
#         CREATE POLICY "Users can insert their own category selections" ON public.user_onboarding_categories
#             FOR INSERT
#             WITH CHECK (auth.uid() = user_id);
#
#         CREATE POLICY "Users can update their own category selections" ON public.user_onboarding_categories
#             FOR UPDATE
#             USING (auth.uid() = user_id)
#             WITH CHECK (auth.uid() = user_id);
#
#         CREATE POLICY "Users can delete their own category selections" ON public.user_onboarding_categories
#             FOR DELETE
#             USING (auth.uid() = user_id);
#         """
#
#         # Execute via RPC call to SQL
#         result = supabase_client.service_client.rpc("exec", {"sql": migration_sql}).execute()
#
#         return {"success": True, "message": "Categories schema fixed successfully"}
#
#     except Exception as e:
#         logger.error(f"Fix categories schema error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Failed to fix schema: {str(e)}")

# @app.get("/api/v1/admin/check-schema", response_model=dict, tags=["Admin"])
# @limiter.limit("5/minute")
# async def check_categories_schema(request: Request, _: None = Depends(require_localhost), user_id: str = Depends(get_current_user_from_session)):
#     """Check the current schema of user_onboarding_categories table"""
#
#     try:
#         if not supabase_client.service_client:
#             raise HTTPException(status_code=500, detail="Service client not available")
#
#         # Try to query the table structure via information_schema
#         schema_query = """
#         SELECT column_name, data_type, is_nullable, column_default
#         FROM information_schema.columns
#         WHERE table_schema = 'public'
#         AND table_name = 'user_onboarding_categories'
#         ORDER BY ordinal_position;
#         """
#
#         try:
#             # Try using RPC to execute the query
#             result = supabase_client.service_client.rpc("sql", {"query": schema_query}).execute()
#             return {"success": True, "schema": result.data}
#         except Exception as e:
#             # If RPC doesn't work, try a simple select to see what happens
#             try:
#                 test_result = supabase_client.service_client.table("user_onboarding_categories").select("*").limit(1).execute()
#                 return {
#                     "success": True,
#                     "message": "Table exists and is accessible",
#                     "sample_data": test_result.data
#                 }
#             except Exception as select_error:
#                 return {
#                     "success": False,
#                     "error": f"Table access failed: {str(select_error)}",
#                     "original_rpc_error": str(e)
#                 }
#
#     except Exception as e:
#         logger.error(f"Check schema error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Failed to check schema: {str(e)}")

# @app.get("/api/v1/system/login-stats", tags=["System"])
# @limiter.limit("10/minute")
# async def get_login_stats(request: Request):
#     """Get statistics about user signups and first-time logins"""
#
#     try:
#         # Get stats from Supabase
#         stats_result = supabase_client.get_signup_stats()
#
#         if not stats_result["success"]:
#             raise HTTPException(status_code=500, detail=f"Failed to get stats: {stats_result.get('error')}")
#
#         return stats_result["data"]
#
#     except Exception as e:
#         logger.error(f"Login stats error: {str(e)}")
#         raise HTTPException(status_code=500, detail="Internal server error")

# =============================================================================
# LISTEN SYSTEM ENDPOINTS
# =============================================================================


@app.get("/api/v1/listen/categories", tags=["Listen"])
async def get_listen_categories(request: Request):
    """Get all active podcast categories for listen system"""
    user_id = get_current_user_id(request)
    try:
        # Use the podcast_service which is already working
        categories = await podcast_service.get_categories()

        return {"categories": categories, "total": len(categories)}
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        raise HTTPException(status_code=500, detail="Failed to get categories")


@app.get("/api/v1/listen/featured", tags=["Listen"])
async def get_featured_content(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get featured podcasts with pagination"""
    user_id = get_current_user_id(request)
    try:
        # Get featured podcasts with pagination
        featured_podcasts, total_count = await podcast_service.get_featured_podcasts(
            limit=limit, offset=offset, user_id=user_id
        )

        return {
            "results": featured_podcasts,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "source": "featured",
        }
    except Exception as e:
        logger.error(f"Error getting featured content: {e}")
        raise HTTPException(status_code=500, detail="Failed to get featured content")


@app.get("/api/v1/listen/category/{category_id}/podcasts", tags=["Listen"])
async def get_podcasts_by_category(
    request: Request, category_id: str, limit: int = 20, offset: int = 0
):
    """Get podcasts in a specific category"""
    user_id = get_current_user_id(request)
    try:
        podcasts, total = await podcast_service.get_podcasts_by_category(
            category_id, limit, offset, user_id
        )
        return {
            "results": podcasts,
            "total": total,
            "limit": limit,
            "offset": offset,
            "source": "category",
            "category_id": category_id,
        }
    except Exception as e:
        logger.error(f"Error getting podcasts by category: {e}")
        raise HTTPException(status_code=500, detail="Failed to get podcasts")


@app.get("/api/v1/listen/podcast/{podcast_id}", tags=["Listen"])
async def get_podcast_details(podcast_id: str, request: Request):
    """Get detailed podcast information"""
    user_id = get_current_user_id(request)
    try:
        # Invalidate episode cache for this podcast to fetch fresh data
        podcast_service.episode_cache.invalidate_podcast(podcast_id)
        logger.info(f"Invalidated episode cache for podcast {podcast_id} on user view")

        podcast = await podcast_service.get_podcast_details(podcast_id, user_id)
        if not podcast:
            raise HTTPException(status_code=404, detail="Podcast not found")

        return podcast
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting podcast details: {e}")
        raise HTTPException(status_code=500, detail="Failed to get podcast details")


# @app.get("/api/v1/admin/podcast/{podcast_id}/categories", tags=["Admin"])
# async def get_podcast_categories(
#     podcast_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Get all categories for a podcast"""
#     try:
#         categories = await podcast_service.get_podcast_categories(podcast_id)
#         return {"categories": categories}
#     except Exception as e:
#         logger.error(f"Error getting podcast categories: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get podcast categories")


class SetPodcastCategoriesRequest(BaseModel):
    category_ids: List[str]


# @app.post("/api/v1/admin/podcast/{podcast_id}/categories", tags=["Admin"])
# async def set_podcast_categories(
#     podcast_id: str,
#     request: Request,
#     categories_data: SetPodcastCategoriesRequest,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Set all categories for a podcast (replaces existing)"""
#     try:
#         success = await podcast_service.set_podcast_categories(podcast_id, categories_data.category_ids)
#         if success:
#             return {"success": True, "message": f"Set {len(categories_data.category_ids)} categories for podcast"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to set podcast categories")
#     except Exception as e:
#         logger.error(f"Error setting podcast categories: {e}")
#         raise HTTPException(status_code=500, detail="Failed to set podcast categories")

# @app.post("/api/v1/admin/podcast/{podcast_id}/categories/{category_id}", tags=["Admin"])
# async def add_podcast_to_category(
#     podcast_id: str,
#     category_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Add a podcast to a category"""
#     try:
#         success = await podcast_service.add_podcast_to_category(podcast_id, category_id)
#         if success:
#             return {"success": True, "message": "Podcast added to category"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to add podcast to category")
#     except Exception as e:
#         logger.error(f"Error adding podcast to category: {e}")
#         raise HTTPException(status_code=500, detail="Failed to add podcast to category")

# @app.delete("/api/v1/admin/podcast/{podcast_id}/categories/{category_id}", tags=["Admin"])
# async def remove_podcast_from_category(
#     podcast_id: str,
#     category_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Remove a podcast from a category"""
#     try:
#         success = await podcast_service.remove_podcast_from_category(podcast_id, category_id)
#         if success:
#             return {"success": True, "message": "Podcast removed from category"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to remove podcast from category")
#     except Exception as e:
#         logger.error(f"Error removing podcast from category: {e}")
#         raise HTTPException(status_code=500, detail="Failed to remove podcast from category")

# FEATURED PODCAST CATEGORY MANAGEMENT

# @app.get("/api/v1/admin/featured-podcast/{featured_podcast_id}/categories", tags=["Admin"])
# async def get_featured_podcast_categories(
#     featured_podcast_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Get all categories for a featured podcast"""
#     try:
#         categories = await podcast_service.get_featured_podcast_categories(featured_podcast_id)
#         return {"categories": categories}
#     except Exception as e:
#         logger.error(f"Error getting featured podcast categories: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get featured podcast categories")


class SetFeaturedPodcastCategoriesRequest(BaseModel):
    category_ids: List[str]


# @app.post("/api/v1/admin/featured-podcast/{featured_podcast_id}/categories", tags=["Admin"])
# async def set_featured_podcast_categories(
#     featured_podcast_id: str,
#     request: Request,
#     categories_data: SetFeaturedPodcastCategoriesRequest,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Set all categories for a featured podcast (replaces existing)"""
#     try:
#         success = await podcast_service.set_featured_podcast_categories(featured_podcast_id, categories_data.category_ids)
#         if success:
#             return {"success": True, "message": f"Set {len(categories_data.category_ids)} categories for featured podcast"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to set featured podcast categories")
#     except Exception as e:
#         logger.error(f"Error setting featured podcast categories: {e}")
#         raise HTTPException(status_code=500, detail="Failed to set featured podcast categories")

# @app.post("/api/v1/admin/featured-podcast/{featured_podcast_id}/categories/{category_id}", tags=["Admin"])
# async def add_featured_podcast_to_category(
#     featured_podcast_id: str,
#     category_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Add a featured podcast to a category"""
#     try:
#         success = await podcast_service.add_featured_podcast_to_category(featured_podcast_id, category_id)
#         if success:
#             return {"success": True, "message": "Featured podcast added to category"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to add featured podcast to category")
#     except Exception as e:
#         logger.error(f"Error adding featured podcast to category: {e}")
#         raise HTTPException(status_code=500, detail="Failed to add featured podcast to category")

# @app.delete("/api/v1/admin/featured-podcast/{featured_podcast_id}/categories/{category_id}", tags=["Admin"])
# async def remove_featured_podcast_from_category(
#     featured_podcast_id: str,
#     category_id: str,
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Remove a featured podcast from a category"""
#     try:
#         success = await podcast_service.remove_featured_podcast_from_category(featured_podcast_id, category_id)
#         if success:
#             return {"success": True, "message": "Featured podcast removed from category"}
#         else:
#             raise HTTPException(status_code=500, detail="Failed to remove featured podcast from category")
#     except Exception as e:
#         logger.error(f"Error removing featured podcast from category: {e}")
#         raise HTTPException(status_code=500, detail="Failed to remove featured podcast from category")

# DEBUG ENDPOINT FOR AUTO-FOLLOWS
# @app.post("/api/v1/admin/debug/auto-follow", tags=["Admin"])
# async def debug_auto_follow(
#     request: Request,
#     _: None = Depends(require_localhost),
#     user_id: str = Depends(get_current_user_from_session)
# ):
#     """Debug endpoint to manually trigger auto-follow for current user"""
#     try:
#         # Trigger the auto-follow functionality manually
#         result = supabase_client._create_follows_from_onboarding(
#             user_id=user_id,
#             favorite_podcast_ids=[],  # No user favorites for this test
#             automatic_favorites=AUTOMATIC_FAVORITE_PODCASTS
#         )
#
#         if result["success"]:
#             return {
#                 "success": True,
#                 "message": f"Auto-follow completed",
#                 "data": result.get("data", []),
#                 "auto_podcasts": AUTOMATIC_FAVORITE_PODCASTS
#             }
#         else:
#             return {
#                 "success": False,
#                 "message": f"Auto-follow failed: {result.get('error')}",
#                 "auto_podcasts": AUTOMATIC_FAVORITE_PODCASTS
#             }
#     except Exception as e:
#         logger.error(f"Error in debug auto-follow: {e}")
#         raise HTTPException(status_code=500, detail=f"Debug auto-follow failed: {str(e)}")


@app.get("/api/v1/listen/podcast/{podcast_id}/episodes", tags=["Listen"])
async def get_podcast_episodes(
    podcast_id: str, request: Request, limit: int = 50, offset: int = 0
):
    """Get episodes for a podcast with pagination support"""
    user_id = get_current_user_id(request)
    try:
        episodes, total = await podcast_service.get_podcast_episodes(
            podcast_id, limit, offset, user_id
        )
        return {"episodes": episodes, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Error getting podcast episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get episodes")


@app.get("/api/v1/listen/search/podcasts", tags=["Listen"])
async def search_podcasts(
    request: Request,
    q: str,
    category_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Search podcasts"""
    user_id = get_current_user_id(request)
    try:
        if not validate_search_query(q):
            raise HTTPException(status_code=400, detail="Invalid search query")

        podcasts, total = await podcast_service.search_podcasts(
            q, category_id, limit, offset, user_id
        )
        return {
            "podcasts": podcasts,
            "total": total,
            "query": q,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching podcasts: {e}")
        raise HTTPException(status_code=500, detail="Failed to search podcasts")


@app.get("/api/v1/listen/search/episodes", tags=["Listen"])
async def search_episodes(
    request: Request,
    q: str,
    podcast_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Search episodes"""
    user_id = get_current_user_id(request)
    try:
        if not validate_search_query(q):
            raise HTTPException(status_code=400, detail="Invalid search query")

        episodes, total = await podcast_service.search_episodes(
            q, podcast_id, limit, offset
        )
        return {
            "episodes": episodes,
            "total": total,
            "query": q,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to search episodes")


@app.get("/api/v1/listen/all-podcasts", tags=["Listen"])
async def get_all_podcasts(
    request: Request,
    limit: int = Query(
        100, ge=1, le=100, description="Number of results to return (max 100)"
    ),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get all podcasts from ListenNotes that were created after Jan 1, 2021"""
    user_id = get_current_user_id(request)
    try:
        podcasts, total_count = await podcast_service.get_all_podcasts_from_listennotes(
            limit, offset, user_id
        )
        return {
            "podcasts": podcasts,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(podcasts) < total_count,
            "source": "listennotes",
            "criteria": "Created after Jan 1, 2021",
        }
    except Exception as e:
        logger.error(f"Error getting all podcasts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get all podcasts")


# User listening endpoints (require authentication)


@app.post("/api/v1/listen/podcast/{podcast_id}/follow", tags=["Listen"])
async def follow_podcast(
    podcast_id: str, request: Request, notification_enabled: bool = True
):
    """Follow a podcast"""
    try:
        user_id = get_current_user_id(request)
        result = await user_listening_service.follow_podcast(user_id, podcast_id, notification_enabled)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        # Invalidate episode cache for this podcast to fetch fresh episodes
        podcast_service.episode_cache.invalidate_podcast(podcast_id)
        logger.info(f"Invalidated episode cache for podcast {podcast_id} on user follow")

        # Queue email notification for podcast owner if claimed
        try:
            # Get podcast's listennotes_id first
            podcast_result = supabase_client.service_client.table("podcasts").select(
                "listennotes_id"
            ).eq("id", podcast_id).single().execute()

            if podcast_result.data and podcast_result.data.get("listennotes_id"):
                listennotes_id = podcast_result.data["listennotes_id"]

                # Get podcast owner from podcast_claims table using listennotes_id
                claim_result = supabase_client.service_client.table("podcast_claims").select(
                    "user_id"
                ).eq("listennotes_id", listennotes_id).eq("is_verified", True).eq("claim_status", "verified").execute()

                if claim_result.data and len(claim_result.data) > 0:
                    podcast_owner_id = claim_result.data[0]["user_id"]

                    # Don't notify if user is following their own podcast
                    if podcast_owner_id != user_id:
                        from background_tasks import send_activity_notification_email
                        from email_notification_service import NOTIFICATION_TYPE_PODCAST_FOLLOW

                        # Send email immediately as background task (non-blocking)
                        asyncio.create_task(send_activity_notification_email(
                            user_id=podcast_owner_id,
                            notification_type=NOTIFICATION_TYPE_PODCAST_FOLLOW,
                            actor_id=user_id,
                            resource_id=podcast_id
                        ))
        except Exception as email_error:
            logger.warning(f"Failed to send podcast follow email notification: {email_error}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error following podcast: {e}")
        raise HTTPException(status_code=500, detail="Failed to follow podcast")


@app.delete("/api/v1/listen/podcast/{podcast_id}/follow", tags=["Listen"])
async def unfollow_podcast(podcast_id: str, request: Request):
    """Unfollow a podcast"""
    try:
        user_id = get_current_user_id(request)
        result = await user_listening_service.unfollow_podcast(user_id, podcast_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unfollowing podcast: {e}")
        raise HTTPException(status_code=500, detail="Failed to unfollow podcast")


@app.get("/api/v1/listen/my/follows", tags=["Listen"])
async def get_user_follows(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get user's followed podcasts with pagination"""
    try:
        user_id = get_current_user_id(request)
        follows = await user_listening_service.get_user_followed_podcasts(
            user_id, limit, offset
        )

        # Get total count for pagination metadata
        total_result = await user_listening_service.get_user_followed_podcasts_count(
            user_id
        )
        total_count = total_result.get("count", 0)

        return {
            "follows": follows,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total_count,
                "has_more": offset + len(follows) < total_count,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user follows: {e}")
        raise HTTPException(status_code=500, detail="Failed to get follows")


@app.post("/api/v1/listen/episode/{episode_id}/save", tags=["Listen"])
async def save_episode(episode_id: str, request: Request, notes: Optional[str] = None):
    """Save/bookmark an episode"""
    try:
        user_id = get_current_user_id(request)
        result = await user_listening_service.save_episode(user_id, episode_id, notes)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving episode: {e}")
        raise HTTPException(status_code=500, detail="Failed to save episode")


@app.delete("/api/v1/listen/episode/{episode_id}/save", tags=["Listen"])
async def unsave_episode(episode_id: str, request: Request):
    """Remove episode from saves"""
    try:
        user_id = get_current_user_id(request)
        result = await user_listening_service.unsave_episode(user_id, episode_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsaving episode: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsave episode")


@app.get("/api/v1/listen/my/saved", tags=["Listen"])
async def get_user_saved_episodes(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get user's saved episodes with pagination"""
    try:
        user_id = get_current_user_id(request)
        saves = await user_listening_service.get_user_saved_episodes(
            user_id, limit, offset
        )

        # Get total count for pagination metadata
        total_result = await user_listening_service.get_user_saved_episodes_count(
            user_id
        )
        total_count = total_result.get("count", 0)

        # Transform the saves to use episode_id as the primary id for frontend consistency
        transformed_saves = []
        for save in saves:
            episode_data = save.get("episodes", {})
            transformed_save = {
                "id": save.get(
                    "episode_id"
                ),  # Use episode_id as the primary id for deletion
                "save_id": save.get("id"),  # Keep the save record ID for reference
                "episode_id": save.get("episode_id"),  # Keep explicit episode_id field
                "saved_at": save.get("saved_at"),
                "notes": save.get("notes"),
                "user_id": save.get("user_id"),
                "episode": episode_data,  # Include full episode data
            }
            transformed_saves.append(transformed_save)

        return {
            "saves": transformed_saves,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total_count,
                "has_more": offset + len(saves) < total_count,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting saved episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get saved episodes")


# Initialize episode listen service
episode_listen_service = EpisodeListenService()


@app.post("/api/v1/listen/episode/{episode_id}/start", tags=["Listen"])
async def record_episode_listen_start(episode_id: str, request: Request):
    """
    Record when a user starts listening to an episode.
    This endpoint is specifically for tracking first listens and triggering notifications.

    Call this endpoint when:
    - User clicks play on an episode for the first time
    - User starts listening to a new episode

    This is separate from the progress endpoint to ensure we capture the exact moment
    a user begins listening, which triggers email notifications to podcast owners.
    """
    try:
        user_id = get_current_user_id(request)
        logger.info(f"🎧 Recording episode listen start: user={user_id}, episode={episode_id}")

        # Get episode details to find podcast
        episode_result = supabase_client.service_client.table("episodes").select(
            "podcast_id, title"
        ).eq("id", episode_id).single().execute()

        if not episode_result.data:
            logger.warning(f"Episode {episode_id} not found")
            raise HTTPException(status_code=404, detail="Episode not found")

        podcast_id = episode_result.data["podcast_id"]
        episode_title = episode_result.data.get("title", "Unknown Episode")

        # Record the listen
        result = episode_listen_service.record_episode_listen(
            user_id=user_id,
            episode_id=episode_id,
            podcast_id=podcast_id
        )

        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to record listen"))

        is_first_listen = result["is_first_listen"]

        # Send notification to podcast owner if this is a first listen
        if is_first_listen:
            try:
                logger.info(f"📧 First listen detected - checking for podcast owner to notify...")

                # Get podcast's listennotes_id
                podcast_result = supabase_client.service_client.table("podcasts").select(
                    "listennotes_id, title"
                ).eq("id", podcast_id).single().execute()

                if podcast_result.data and podcast_result.data.get("listennotes_id"):
                    listennotes_id = podcast_result.data["listennotes_id"]
                    podcast_title = podcast_result.data.get("title", "Unknown Podcast")
                    logger.info(f"Found podcast: {podcast_title} (listennotes_id: {listennotes_id})")

                    # Get podcast owner from podcast_claims table
                    claim_result = supabase_client.service_client.table("podcast_claims").select(
                        "user_id"
                    ).eq("listennotes_id", listennotes_id).eq("is_verified", True).eq("claim_status", "verified").execute()

                    if claim_result.data and len(claim_result.data) > 0:
                        podcast_owner_id = claim_result.data[0]["user_id"]
                        logger.info(f"Found podcast owner: {podcast_owner_id}")

                        # Don't notify if user is listening to their own podcast
                        if podcast_owner_id != user_id:
                            from background_tasks import send_activity_notification_email
                            from email_notification_service import NOTIFICATION_TYPE_PODCAST_LISTEN

                            logger.info(f"✅ Sending podcast listen notification email to owner {podcast_owner_id}")
                            # Send email immediately as background task (non-blocking)
                            import asyncio
                            asyncio.create_task(send_activity_notification_email(
                                user_id=podcast_owner_id,
                                notification_type=NOTIFICATION_TYPE_PODCAST_LISTEN,
                                actor_id=user_id,
                                resource_id=episode_id
                            ))
                        else:
                            logger.info(f"Skipping notification - user listening to their own podcast")
                    else:
                        logger.info(f"No verified owner found for podcast with listennotes_id {listennotes_id}")
                else:
                    logger.info(f"No listennotes_id found for podcast {podcast_id}")
            except Exception as email_error:
                # Don't fail the request if notification fails
                logger.error(f"❌ Failed to send podcast listen notification: {email_error}", exc_info=True)

        return RecordEpisodeListenResponse(
            success=True,
            is_first_listen=is_first_listen,
            error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recording episode listen: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to record episode listen")


@app.get("/api/v1/listen/episode/{episode_id}/progress", tags=["Listen"])
async def get_episode_progress(episode_id: str, request: Request):
    """Get listening progress for an episode"""
    try:
        user_id = get_current_user_id(request)
        result = await user_listening_service.get_episode_progress(user_id, episode_id)

        if not result["success"]:
            status_code = 404 if result.get("error_code") == "NOT_FOUND" else 400
            raise HTTPException(status_code=status_code, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting episode progress: {e}")
        raise HTTPException(status_code=500, detail="Failed to get episode progress")


@app.post("/api/v1/listen/episode/{episode_id}/progress", tags=["Listen"])
async def update_listening_progress(
    episode_id: str, request: Request, body: ListeningProgressRequest
):
    """
    Update listening progress for an episode.

    Note: This endpoint only tracks playback progress. First listen notifications
    are now handled by the /api/v1/listen/episode/{episode_id}/start endpoint.
    """
    try:
        user_id = get_current_user_id(request)
        logger.info(f"📊 Listening progress update: user={user_id}, episode={episode_id}, progress={body.progress_seconds}s")

        result = await user_listening_service.update_listening_progress(
            user_id,
            episode_id,
            body.progress_seconds,
            body.duration_seconds,
            body.playback_speed,
        )

        if not result["success"]:
            # Use appropriate status code based on error
            status_code = 400
            if result.get("error_code") == "EPISODE_NOT_FOUND":
                status_code = 404
            raise HTTPException(status_code=status_code, detail=result["message"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating progress: {e}")
        raise HTTPException(status_code=500, detail="Failed to update progress")


@app.get("/api/v1/listen/my/continue-listening", tags=["Listen"])
async def get_continue_listening(
    request: Request,
    limit: int = Query(10, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """Get episodes user is currently listening to with pagination"""
    try:
        user_id = get_current_user_id(request)
        episodes = await user_listening_service.get_continue_listening(
            user_id, limit, offset
        )

        # Get total count for pagination metadata
        total_result = await user_listening_service.get_continue_listening_count(
            user_id
        )
        total_count = total_result.get("count", 0)

        return {
            "episodes": episodes,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total_count,
                "has_more": offset + len(episodes) < total_count,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting continue listening: {e}")
        raise HTTPException(status_code=500, detail="Failed to get continue listening")


@app.get("/api/v1/listen/my/history", tags=["Listen"])
async def get_listening_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    completed_only: bool = False,
):
    """Get user's listening history with pagination"""
    try:
        user_id = get_current_user_id(request)
        history = await user_listening_service.get_listening_history(
            user_id, limit, offset, completed_only
        )

        # Get total count for pagination metadata
        total_result = await user_listening_service.get_listening_history_count(
            user_id, completed_only
        )
        total_count = total_result.get("count", 0)

        return {
            "history": history,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "total": total_count,
                "has_more": offset + len(history) < total_count,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting listening history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get listening history")


# @app.post("/api/v1/admin/podcast/{podcast_id}/refresh-episodes", tags=["Admin"])
# async def refresh_podcast_episodes(
#     podcast_id: str,
#     request: Request
# ):
#     """Admin endpoint to refresh episodes for a specific podcast"""
#     try:
#         # This should be protected by admin authentication in production
#         logger.info(f"Refreshing episodes for podcast {podcast_id}")
#
#         # Get podcast details
#         podcast_details = await podcast_service.get_podcast_details(podcast_id)
#         if not podcast_details:
#             raise HTTPException(status_code=404, detail="Podcast not found")
#
#         listennotes_id = podcast_details.get('listennotes_id')
#         if not listennotes_id:
#             raise HTTPException(status_code=400, detail="Podcast has no ListenNotes ID")
#
#         # Force refresh episodes
#         success = await podcast_service._import_episodes_on_demand(podcast_id)
#
#         if success:
#             # Also explicitly update the latest_episode_id
#             await podcast_service.update_podcast_latest_episode_id(podcast_id)
#
#             # Get updated podcast details
#             updated_details = await podcast_service.get_podcast_details(podcast_id)
#
#             return {
#                 "success": True,
#                 "message": "Episodes refreshed successfully",
#                 "podcast": {
#                     "id": podcast_id,
#                     "title": updated_details.get('title'),
#                     "latest_episode": updated_details.get('most_recent_episode')
#                 }
#             }
#         else:
#             raise HTTPException(status_code=500, detail="Failed to refresh episodes")
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error refreshing podcast episodes: {e}")
#         raise HTTPException(status_code=500, detail="Failed to refresh episodes")

# @app.post("/api/v1/admin/podcast/{podcast_id}/update-latest-episode", tags=["Admin"])
# async def update_podcast_latest_episode(
#     podcast_id: str,
#     request: Request
# ):
#     """Admin endpoint to update latest_episode_id for a specific podcast"""
#     try:
#         logger.info(f"Updating latest_episode_id for podcast {podcast_id}")
#
#         # Use the database function to update latest_episode_id
#         result = supabase.rpc('update_podcast_latest_episode', {'p_podcast_id': podcast_id}).execute()
#
#         if result.data:
#             # Get updated podcast details
#             podcast_result = supabase.table('podcasts') \
#                 .select('latest_episode_id, title') \
#                 .eq('id', podcast_id) \
#                 .single() \
#                 .execute()
#
#             if podcast_result.data:
#                 latest_episode_id = podcast_result.data['latest_episode_id']
#
#                 # Get episode details
#                 episode_result = supabase.table('episodes') \
#                     .select('listennotes_id, title, published_at') \
#                     .eq('id', latest_episode_id) \
#                     .single() \
#                     .execute()
#
#                 episode_info = episode_result.data if episode_result.data else None
#
#                 return {
#                     "success": True,
#                     "message": "Latest episode ID updated successfully",
#                     "podcast_id": podcast_id,
#                     "podcast_title": podcast_result.data['title'],
#                     "latest_episode_id": latest_episode_id,
#                     "latest_episode": episode_info
#                 }
#             else:
#                 raise HTTPException(status_code=404, detail="Podcast not found")
#         else:
#             raise HTTPException(status_code=404, detail="No episodes found for this podcast")
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error updating latest episode ID: {e}")
#         raise HTTPException(status_code=500, detail="Failed to update latest episode ID")

# @app.post("/api/v1/admin/refresh-featured-episodes", tags=["Admin"])
# async def manual_refresh_featured_episodes(request: Request):
#     """Admin endpoint to manually trigger featured podcast episode cache refresh"""
#     try:
#         logger.info("Manually triggering featured podcast episode cache refresh")
#
#         from background_tasks import refresh_featured_podcast_episodes
#         result = await refresh_featured_podcast_episodes()
#
#         return {
#             "success": result["success"],
#             "message": "Featured podcast episode cache refresh completed",
#             "results": result
#         }
#
#     except Exception as e:
#         logger.error(f"Error triggering featured episode refresh: {e}")
#         raise HTTPException(status_code=500, detail="Failed to refresh featured episodes")

# @app.post("/api/v1/admin/refresh-stale-episodes", tags=["Admin"])
# async def manual_refresh_stale_episodes(request: Request):
#     """Admin endpoint to manually trigger stale podcast episode cache refresh"""
#     try:
#         logger.info("Manually triggering stale podcast episode cache refresh")
#
#         from background_tasks import refresh_stale_podcast_episodes
#         result = await refresh_stale_podcast_episodes()
#
#         return {
#             "success": result["success"],
#             "message": "Stale podcast episode cache refresh completed",
#             "results": result
#         }
#
#     except Exception as e:
#         logger.error(f"Error triggering stale episode refresh: {e}")
#         raise HTTPException(status_code=500, detail="Failed to refresh stale episodes")

# @app.get("/api/v1/admin/background-jobs/status", tags=["Admin"])
# async def get_background_jobs_status(request: Request):
#     """Admin endpoint to get status of all background jobs"""
#     try:
#         job_status = scheduler_service.get_job_status()
#         return job_status
#
#     except Exception as e:
#         logger.error(f"Error getting background job status: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get background job status")


# =============================================================================
# MESSAGES SYSTEM ENDPOINTS
# =============================================================================

# Conversations


@app.get("/api/v1/messages/conversations", tags=["Messages"])
async def get_conversations(
    request: Request, limit: int = 20, offset: int = 0, include_archived: bool = False
):
    """Get user's conversations with latest messages"""
    try:
        user_id = get_current_user_id(request)
        conversations = await messages_service.get_user_conversations(
            user_id, limit, offset, include_archived
        )
        return {"conversations": conversations}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get conversations")


@app.post("/api/v1/messages/conversations", tags=["Messages"])
async def create_conversation(request: Request, participant_id: str):
    """Create a new direct conversation between two users"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.create_conversation(
            creator_id=user_id, participant_ids=[participant_id]
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create conversation")


@app.get("/api/v1/messages/conversations/{conversation_id}", tags=["Messages"])
async def get_conversation_details(request: Request, conversation_id: str):
    """Get detailed conversation information"""
    try:
        user_id = get_current_user_id(request)
        conversation = await messages_service.get_conversation_details(
            conversation_id, user_id
        )

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return conversation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation details: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get conversation details"
        )


@app.get("/api/v1/messages/users", tags=["Messages"])
async def get_messageable_users(request: Request, limit: int = 50, offset: int = 0):
    """Get list of users available for direct messaging"""
    try:
        user_id = get_current_user_id(request)
        users = await messages_service.get_messageable_users(user_id, limit, offset)
        return {"users": users}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messageable users: {e}")
        raise HTTPException(status_code=500, detail="Failed to get users")


@app.delete("/api/v1/messages/conversations/{conversation_id}", tags=["Messages"])
async def delete_conversation(request: Request, conversation_id: str):
    """Delete a conversation (remove user as participant)"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.delete_conversation(conversation_id, user_id)

        if result["success"]:
            return result
        else:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Failed to delete conversation"),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


# Messages


@app.get("/api/v1/messages/conversations/{conversation_id}/messages", tags=["Messages"])
async def get_messages(
    request: Request,
    conversation_id: str,
    limit: int = 50,
    before_message_id: Optional[str] = None,
    after_message_id: Optional[str] = None,
):
    """Get messages for a conversation with pagination"""
    try:
        user_id = get_current_user_id(request)
        messages, has_more = await messages_service.get_conversation_messages(
            conversation_id=conversation_id,
            user_id=user_id,
            limit=limit,
            before_message_id=before_message_id,
            after_message_id=after_message_id,
        )

        return {"messages": messages, "has_more": has_more}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to get messages")


class AttachmentData(BaseModel):
    """Single file attachment data"""

    url: str
    type: str
    filename: str
    size: int
    mime_type: str


class VoiceData(BaseModel):
    """Voice message data"""

    audio_url: str
    duration_seconds: Optional[float] = None
    waveform: Optional[List[float]] = None


class PodcastShareData(BaseModel):
    """Podcast/episode sharing data"""

    podcast_id: Optional[str] = None
    episode_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    content: Optional[str] = None
    message_type: str = "text"
    attachment_data: Optional[AttachmentData] = None
    voice_data: Optional[VoiceData] = None
    podcast_share_data: Optional[PodcastShareData] = None
    reply_to_message_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "content": "Hello! Check out this file.",
                "message_type": "text",
                "attachment_data": {
                    "url": "https://storage.example.com/files/document.pdf",
                    "type": "document",
                    "filename": "document.pdf",
                    "size": 1048576,
                    "mime_type": "application/pdf",
                },
                "reply_to_message_id": None,
            }
        }


class EditMessageRequest(BaseModel):
    content: str


class MessageReactionRequest(BaseModel):
    reaction_type: str = Field(
        ...,
        description="Emoji or reaction name (e.g., '👍', '❤️', 'like'). Empty string to remove reaction.",
    )

    class Config:
        json_schema_extra = {"example": {"reaction_type": "👍"}}


@app.post(
    "/api/v1/messages/conversations/{conversation_id}/messages", tags=["Messages"]
)
async def send_message(
    request: Request, conversation_id: str, message_request: SendMessageRequest
):
    """Send a message in a conversation"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.send_message(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=message_request.content,
            message_type=message_request.message_type,
            attachment_data=message_request.attachment_data,
            voice_data=message_request.voice_data,
            podcast_share_data=message_request.podcast_share_data,
            reply_to_message_id=message_request.reply_to_message_id,
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        # Send notification to recipient
        try:
            # Get conversation participants to find the recipient
            participants_result = (
                messages_service.supabase.table("conversation_participants")
                .select("user_id")
                .eq("conversation_id", conversation_id)
                .neq("user_id", user_id)
                .is_("left_at", "null")
                .execute()
            )

            if participants_result.data and len(participants_result.data) > 0:
                recipient_id = participants_result.data[0]["user_id"]

                # Get sender's name from the current user
                user_profile_service = UserProfileService()
                sender_profile = await user_profile_service.get_user_profile(user_id)
                sender_name = sender_profile.get("name", "Someone")

                # Create notification
                notification_service = NotificationService()
                message_preview = message_request.content or "Sent a message"
                await notification_service.notify_new_message(
                    recipient_id=recipient_id,
                    sender_id=user_id,
                    sender_name=sender_name,
                    message_id=result["data"]["id"],
                    message_preview=message_preview,
                )

                # Send email notification for recipient (background task)
                try:
                    from background_tasks import send_activity_notification_email
                    from email_notification_service import NOTIFICATION_TYPE_NEW_MESSAGE

                    # Send email immediately as background task (non-blocking)
                    asyncio.create_task(send_activity_notification_email(
                        user_id=recipient_id,
                        notification_type=NOTIFICATION_TYPE_NEW_MESSAGE,
                        actor_id=user_id,
                        resource_id=conversation_id
                    ))
                except Exception as email_error:
                    logger.warning(f"Failed to send new message email notification: {email_error}")

        except Exception as e:
            logger.warning(f"Failed to send message notification: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail="Failed to send message")


@app.post("/api/v1/messages/conversations/{conversation_id}/voice", tags=["Messages"])
async def send_voice_message(
    request: Request,
    conversation_id: str,
    audio_file: UploadFile = File(...),
    duration_seconds: Optional[float] = None,
):
    """Send a voice message in a conversation"""
    try:
        user_id = get_current_user_id(request)

        # Validate file type
        allowed_types = [
            "audio/webm",
            "audio/mp3",
            "audio/mpeg",
            "audio/wav",
            "audio/ogg",
        ]
        if audio_file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid audio format. Allowed types: {', '.join(allowed_types)}",
            )

        # Read file content
        file_content = await audio_file.read()

        # Upload to R2 storage
        file_extension = (
            audio_file.filename.split(".")[-1] if "." in audio_file.filename else "webm"
        )
        storage_path = f"voice_messages/{conversation_id}/{user_id}_{datetime.now().timestamp()}.{file_extension}"

        audio_url = await media_service._upload_to_storage(
            file_content=file_content,
            storage_path=storage_path,
            mime_type=audio_file.content_type,
        )

        # Send voice message
        result = await messages_service.send_message(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=None,  # No text content for voice messages
            message_type="voice",
            voice_data={"audio_url": audio_url, "duration_seconds": duration_seconds},
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending voice message: {e}")
        raise HTTPException(status_code=500, detail="Failed to send voice message")


@app.post(
    "/api/v1/messages/conversations/{conversation_id}/messages/media", tags=["Messages"]
)
async def send_message_with_media(
    request: Request,
    conversation_id: str,
    content: Optional[str] = Form(None),
    message_type: str = Form("text"),
    reply_to_message_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    """Send a message with multiple media attachments (images, videos, documents)"""
    try:
        user_id = get_current_user_id(request)

        # Validate at least one file is provided
        if not files or len(files) == 0:
            raise HTTPException(
                status_code=400, detail="At least one media file is required"
            )

        # Validate file count (max 10 files per message)
        if len(files) > 10:
            raise HTTPException(
                status_code=400, detail="Maximum 10 files allowed per message"
            )

        # Send message with media files
        result = await messages_service.send_message(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=content,
            message_type=message_type,
            reply_to_message_id=reply_to_message_id,
            media_files=files,
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message with media: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to send message with media: {str(e)}"
        )


@app.get("/api/v1/messages/{message_id}/media", tags=["Messages"])
async def get_message_media(request: Request, message_id: str):
    """Get all media attachments for a message with signed URLs"""
    try:
        user_id = get_current_user_id(request)

        from message_media_service import get_message_media_service

        media_service_instance = get_message_media_service()

        media_list = await media_service_instance.get_message_media(user_id, message_id)

        return {"success": True, "data": media_list}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting message media: {e}")
        raise HTTPException(status_code=500, detail="Failed to get message media")


@app.delete("/api/v1/messages/media/{media_id}", tags=["Messages"])
async def delete_message_media(request: Request, media_id: str):
    """Delete a specific media attachment from a message"""
    try:
        user_id = get_current_user_id(request)

        from message_media_service import get_message_media_service

        media_service_instance = get_message_media_service()

        result = await media_service_instance.delete_message_media(user_id, media_id)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting message media: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete message media")


@app.put("/api/v1/messages/{message_id}", tags=["Messages"])
async def edit_message(
    request: Request, message_id: str, edit_request: EditMessageRequest
):
    """Edit a message's content"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.edit_message(
            message_id=message_id, user_id=user_id, new_content=edit_request.content
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        raise HTTPException(status_code=500, detail="Failed to edit message")


@app.delete("/api/v1/messages/{message_id}", tags=["Messages"])
async def delete_message(request: Request, message_id: str):
    """Delete a message"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.delete_message(message_id, user_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete message")


# User Presence


# Read Receipts


@app.post("/api/v1/messages/{message_id}/read", tags=["Messages"])
@limiter.limit("60/minute")
async def mark_message_read(request: Request, message_id: str):
    """Mark a specific message as read"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.mark_message_as_read(message_id, user_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking message as read: {e}")
        raise HTTPException(status_code=500, detail="Failed to mark message as read")


@app.post("/api/v1/messages/conversations/{conversation_id}/read", tags=["Messages"])
@limiter.limit("30/minute")
async def mark_conversation_messages_read(
    request: Request, conversation_id: str, read_data: dict
):
    """Mark all messages up to a specific message as read in a conversation"""
    try:
        user_id = get_current_user_id(request)
        up_to_message_id = read_data.get("up_to_message_id")

        if not up_to_message_id:
            raise HTTPException(status_code=400, detail="up_to_message_id is required")

        result = await messages_service.mark_messages_as_read_up_to(
            conversation_id, user_id, up_to_message_id
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking conversation messages as read: {e}")
        raise HTTPException(status_code=500, detail="Failed to mark messages as read")


@app.get("/api/v1/messages/{message_id}/receipts", tags=["Messages"])
@limiter.limit("60/minute")
async def get_message_receipts(request: Request, message_id: str):
    """Get read receipts for a specific message"""
    try:
        user_id = get_current_user_id(request)
        result = await messages_service.get_message_read_receipts(message_id, user_id)

        if not result["success"]:
            if "not found" in result["error"].lower():
                raise HTTPException(status_code=404, detail=result["error"])
            else:
                raise HTTPException(status_code=400, detail=result["error"])

        return result["data"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting message receipts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get message receipts")


# Message Reactions


@app.post("/api/v1/messages/{message_id}/reactions", tags=["Messages"])
@limiter.limit("60/minute")
async def toggle_message_reaction(
    request: Request, message_id: str, reaction_request: MessageReactionRequest
):
    """Add, update or remove a reaction from a message

    Supported reactions:
    - Emojis: 👍, 👎, ❤️, 😂, 😢, 😡, 😮, 🔥, 💯, 🎉, 😍, 🤔, 👏, 😅, 😊, 🙏, 💪, 👌, 🤝, ✨
    - Names: like, love, laugh, sad, angry, wow, fire, hundred, party

    To remove a reaction, send an empty string for reaction_type.
    """
    try:
        user_id = get_current_user_id(request)

        result = await messages_service.toggle_message_reaction(
            message_id, user_id, reaction_request.reaction_type
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        # Send notification if reaction was added (not removed)
        if (
            result.get("data", {}).get("action") == "added"
            and reaction_request.reaction_type
        ):
            try:
                # Get message details to find the author
                message = await messages_service.get_message(message_id)
                if message and message.get("sender_id"):
                    message_author_id = message["sender_id"]

                    # Get reactor's name
                    user_profile_service = UserProfileService()
                    reactor_profile = await user_profile_service.get_user_profile(
                        user_id
                    )
                    reactor_name = reactor_profile.get("name", "Someone")

                    # Create notification
                    notification_service = NotificationService()
                    await notification_service.notify_message_reaction(
                        message_author_id=message_author_id,
                        reactor_id=user_id,
                        reactor_name=reactor_name,
                        message_id=message_id,
                        emoji=reaction_request.reaction_type,
                    )
            except Exception as e:
                logger.warning(f"Failed to send message reaction notification: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling message reaction: {e}")
        raise HTTPException(status_code=500, detail="Failed to toggle message reaction")


# Search


@app.get("/api/v1/messages/search", tags=["Messages"])
async def search_messages(
    request: Request,
    query: str,
    conversation_id: Optional[str] = None,
    message_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """Search messages across conversations"""
    try:
        user_id = get_current_user_id(request)
        messages, total_count = await messages_service.search_messages(
            user_id=user_id,
            query=query,
            conversation_id=conversation_id,
            message_type=message_type,
            limit=limit,
            offset=offset,
        )

        return {
            "messages": messages,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to search messages")


# =============================================================================
# USER PROFILE ENDPOINTS
# =============================================================================


@app.get("/api/v1/users/{user_id}/profile", tags=["User Profile"])
async def get_user_profile(user_id: str, request: Request):
    """Get complete user profile with interests, location, bio, and connection status"""
    try:
        # Resolve "me" to actual user ID
        if user_id == "me":
            try:
                user_id = get_current_user_id(request)
            except HTTPException:
                raise HTTPException(status_code=401, detail="Authentication required to access your own profile")

        # Check privacy settings - get requesting user ID
        requesting_user_id = None
        try:
            requesting_user_id = get_current_user_id(request)
        except:
            pass  # Not authenticated

        # Check if profile is visible based on privacy settings
        settings_service = get_user_settings_service()
        is_visible = await settings_service.is_user_profile_visible(
            user_id, requesting_user_id
        )

        if not is_visible:
            raise HTTPException(403, "This profile is private")

        profile_service = UserProfileService()
        profile = await profile_service.get_user_profile(user_id)

        # Add connection status if user is authenticated
        try:
            current_user_id = get_current_user_id(request)
            if current_user_id and current_user_id == user_id:
                # Viewing own profile
                profile["connection_status"] = {
                    "status": "self",
                    "connected": False,
                    "connection_id": None,
                    "is_requester": False,
                }
            elif current_user_id and current_user_id != user_id:
                # Get connection status with another user
                from user_connections_service import get_user_connections_service

                connections_service = get_user_connections_service()
                connection_status = await connections_service.check_connection_status(
                    current_user_id, user_id
                )
                profile["connection_status"] = connection_status
            else:
                # Not authenticated
                profile["connection_status"] = None
        except Exception as e:
            # If not authenticated or error getting status, set to None
            logger.error(f"Error getting connection status for user {user_id}: {str(e) if str(e) else 'Unknown error'}", exc_info=True)
            profile["connection_status"] = None

        return {"success": True, "data": profile}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user profile")


@app.put("/api/v1/users/profile", tags=["User Profile"])
async def update_own_profile(request: Request, update_data: UpdateProfileRequest):
    """Update own profile (name, bio, location)"""
    try:
        user_id = get_current_user_id(request)
        profile_service = UserProfileService()

        profile = await profile_service.update_user_profile(
            user_id, update_data.dict(exclude_none=True)
        )

        return {"success": True, "data": profile}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")


@app.post("/api/v1/users/profile/avatar", tags=["User Profile"])
async def upload_avatar(request: Request, avatar: UploadFile = File(...)):
    """Upload/update profile avatar"""
    try:
        user_id = get_current_user_id(request)
        profile_service = UserProfileService()

        result = await profile_service.upload_avatar(user_id, avatar)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading avatar: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload avatar")


@app.delete("/api/v1/users/profile/avatar", tags=["User Profile"])
async def delete_avatar(request: Request):
    """Delete profile avatar"""
    try:
        user_id = get_current_user_id(request)
        profile_service = UserProfileService()

        result = await profile_service.delete_avatar(user_id)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting avatar: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete avatar")


@app.get("/api/v1/users/{user_id}/avatar", tags=["User Profile"])
@limiter.limit("100/minute")
async def get_user_avatar(user_id: str, request: Request):
    """
    Get user's avatar as a presigned URL

    Returns a presigned URL that is valid for 1 hour for secure access to the avatar image.
    If the user has no avatar, returns null for avatar_url.
    """
    try:
        # Resolve "me" to actual user ID
        if user_id == "me":
            try:
                user_id = get_current_user_id(request)
            except HTTPException:
                raise HTTPException(status_code=401, detail="Authentication required to access your own avatar")

        profile_service = UserProfileService()
        result = await profile_service.get_user_avatar(user_id)

        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting avatar for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get avatar")


# =============================================================================
# USER INTERESTS/TOPICS ENDPOINTS
# =============================================================================
# NOTE: These endpoints are disabled for now. Uncomment when ready to use.

# @app.get("/api/v1/topics", tags=["User Interests"])
# async def get_all_topics():
#     """Get available topics for selection"""
#     try:
#         interests_service = get_user_interests_service()
#         topics = await interests_service.get_all_topics()
#         return {"success": True, "data": topics}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting topics: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get topics")


# @app.get("/api/v1/users/{user_id}/interests", tags=["User Interests"])
# async def get_user_interests(user_id: str):
#     """Get user's interests/topics"""
#     try:
#         interests_service = get_user_interests_service()
#         interests = await interests_service.get_user_interests(user_id)
#         return {"success": True, "data": interests}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting user interests: {e}")
#         raise HTTPException(status_code=500, detail="Failed to get user interests")


# @app.put("/api/v1/users/interests", tags=["User Interests"])
# async def update_user_interests(
#     request: Request,
#     interests_data: UpdateInterestsRequest
# ):
#     """Update user's interests/topics"""
#     try:
#         user_id = get_current_user_id(request)
#         interests_service = get_user_interests_service()

#         interests = await interests_service.update_user_interests(
#             user_id,
#             interests_data.topic_ids
#         )

#         return {"success": True, "data": interests}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error updating user interests: {e}")
#         raise HTTPException(status_code=500, detail="Failed to update interests")


# @app.post("/api/v1/users/interests", tags=["User Interests"])
# async def add_user_interest(
#     request: Request,
#     interest_data: AddInterestRequest
# ):
#     """Add a single interest to user's interests"""
#     try:
#         user_id = get_current_user_id(request)
#         interests_service = get_user_interests_service()

#         interest = await interests_service.add_user_interest(
#             user_id,
#             interest_data.topic_id
#         )

#         return {"success": True, "data": interest}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error adding user interest: {e}")
#         raise HTTPException(status_code=500, detail="Failed to add interest")


# @app.delete("/api/v1/users/interests/{topic_id}", tags=["User Interests"])
# async def remove_user_interest(
#     request: Request,
#     topic_id: str
# ):
#     """Remove a single interest from user's interests"""
#     try:
#         user_id = get_current_user_id(request)
#         interests_service = get_user_interests_service()

#         result = await interests_service.remove_user_interest(user_id, topic_id)

#         return result
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error removing user interest: {e}")
#         raise HTTPException(status_code=500, detail="Failed to remove interest")


# =============================================================================
# USER CONNECTIONS ENDPOINTS
# =============================================================================


@app.get("/api/v1/users/{user_id}/connections", tags=["User Connections"])
async def get_user_connections(
    user_id: str,
    request: Request,
    status: Optional[str] = "accepted",
    limit: int = 50,
    offset: int = 0,
):
    """Get user's connections list"""
    try:
        # Try to get viewing user ID if authenticated (optional)
        viewing_user_id = None
        try:
            viewing_user_id = get_current_user_id(request)
        except:
            pass  # Not authenticated, that's fine

        connections_service = get_user_connections_service()
        connections = await connections_service.get_user_connections(
            user_id,
            status=status,
            limit=limit,
            offset=offset,
            viewing_user_id=viewing_user_id,
        )
        return {"success": True, "data": connections}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user connections: {e}")
        raise HTTPException(status_code=500, detail="Failed to get connections")


@app.get("/api/v1/users/connections/pending", tags=["User Connections"])
async def get_pending_connection_requests(request: Request):
    """Get pending connection requests sent to user"""
    try:
        user_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        requests = await connections_service.get_pending_requests(user_id)

        return {"success": True, "data": requests}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending requests: {e}")
        raise HTTPException(status_code=500, detail="Failed to get pending requests")


@app.post("/api/v1/users/{user_id}/connect", tags=["User Connections"])
async def send_connection_request(request: Request, user_id: str):
    """Send connection request to another user"""
    try:
        requester_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        result = await connections_service.send_connection_request(
            requester_id, user_id
        )

        # Invalidate profile cache for both users after connection request
        if result.get("success"):
            try:
                from user_profile_cache_service import get_user_profile_cache_service
                profile_cache = get_user_profile_cache_service()
                profile_cache.invalidate(requester_id)
                profile_cache.invalidate(user_id)
                logger.info(f"Invalidated profile cache for users {requester_id} and {user_id} after connection request")
            except Exception as e:
                logger.warning(f"Failed to invalidate profile cache after connection request (non-fatal): {e}")

            # Send notification for new connection request
            try:
                user_profile_service = UserProfileService()
                requester_profile = await user_profile_service.get_user_profile(
                    requester_id
                )
                requester_name = requester_profile.get("name", "Someone")

                notification_service = NotificationService()
                await notification_service.notify_connection_request(
                    recipient_id=user_id,
                    requester_id=requester_id,
                    requester_name=requester_name,
                )

                # Send email notification for connection request (background task)
                try:
                    from background_tasks import send_activity_notification_email
                    from email_notification_service import NOTIFICATION_TYPE_CONNECTION_REQUEST

                    # Send email immediately as background task (non-blocking)
                    asyncio.create_task(send_activity_notification_email(
                        user_id=user_id,
                        notification_type=NOTIFICATION_TYPE_CONNECTION_REQUEST,
                        actor_id=requester_id,
                        resource_id=None  # No specific resource for connection requests
                    ))
                except Exception as email_error:
                    logger.warning(f"Failed to queue connection request email notification: {email_error}")

            except Exception as e:
                logger.warning(f"Failed to send connection request notification: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending connection request: {e}")
        raise HTTPException(status_code=500, detail="Failed to send connection request")


@app.put("/api/v1/users/connections/{request_id}/accept", tags=["User Connections"])
async def accept_connection_request(request: Request, request_id: str):
    """Accept connection request by request_id (connection record ID)"""
    try:
        user_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        result = await connections_service.accept_connection_request(
            user_id, request_id
        )

        # Invalidate profile cache for both users and send notification
        if result.get("success"):
            try:
                # Get the connection to find the requester
                connection_result = (
                    supabase_client.service_client.table("user_connections")
                    .select("follower_id")
                    .eq("id", request_id)
                    .single()
                    .execute()
                )

                if connection_result.data:
                    requester_id = connection_result.data["follower_id"]

                    # Invalidate profile cache for both users
                    try:
                        from user_profile_cache_service import get_user_profile_cache_service
                        profile_cache = get_user_profile_cache_service()
                        profile_cache.invalidate(requester_id)
                        profile_cache.invalidate(user_id)
                        logger.info(f"Invalidated profile cache for users {requester_id} and {user_id} after connection accepted")
                    except Exception as e:
                        logger.warning(f"Failed to invalidate profile cache after connection accept (non-fatal): {e}")

                    user_profile_service = UserProfileService()
                    accepter_profile = await user_profile_service.get_user_profile(
                        user_id
                    )
                    accepter_name = accepter_profile.get("name", "Someone")

                    notification_service = NotificationService()
                    await notification_service.notify_connection_accepted(
                        requester_id=requester_id,
                        accepter_id=user_id,
                        accepter_name=accepter_name,
                    )
            except Exception as e:
                logger.warning(f"Failed to send connection accepted notification: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error accepting connection request: {e}")
        raise HTTPException(status_code=500, detail="Failed to accept connection")


@app.put("/api/v1/users/connections/{request_id}/decline", tags=["User Connections"])
async def decline_connection_request(request: Request, request_id: str):
    """Decline connection request"""
    try:
        user_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        result = await connections_service.decline_connection_request(
            user_id, request_id
        )

        # Invalidate profile cache for both users after connection declined
        if result.get("success"):
            try:
                # Get the connection to find the requester
                connection_result = supabase_client.service_client.table("user_connections").select(
                    "follower_id"
                ).eq("id", request_id).single().execute()

                if connection_result.data:
                    requester_id = connection_result.data["follower_id"]

                    from user_profile_cache_service import get_user_profile_cache_service
                    profile_cache = get_user_profile_cache_service()
                    profile_cache.invalidate(requester_id)
                    profile_cache.invalidate(user_id)
                    logger.info(f"Invalidated profile cache for users {requester_id} and {user_id} after connection declined")
            except Exception as e:
                logger.warning(f"Failed to invalidate profile cache after connection decline (non-fatal): {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error declining connection request: {e}")
        raise HTTPException(status_code=500, detail="Failed to decline connection")


@app.delete("/api/v1/users/connections/{connection_id}", tags=["User Connections"])
async def remove_connection(request: Request, connection_id: str):
    """Remove/cancel a connection"""
    try:
        user_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        result = await connections_service.remove_connection(user_id, connection_id)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing connection: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove connection")


@app.get("/api/v1/users/{user_id}/connection-status", tags=["User Connections"])
async def check_connection_status(request: Request, user_id: str):
    """Check connection status with another user"""
    try:
        current_user_id = get_current_user_id(request)
        connections_service = get_user_connections_service()

        status = await connections_service.check_connection_status(
            current_user_id, user_id
        )

        return {"success": True, "data": status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking connection status: {e}")
        raise HTTPException(status_code=500, detail="Failed to check connection status")


@app.get("/api/v1/users/connections/suggested", tags=["User Connections"])
async def get_suggested_connections(request: Request, limit: int = 20, offset: int = 0):
    """
    Get suggested users to connect with

    Returns users that the current user is not already connected to
    and has no pending connection requests with.
    """
    try:
        user_id = get_current_user_id(request)
        logger.info(
            f"[SUGGESTED CONNECTIONS] Getting suggestions for user_id: {user_id}"
        )
        connections_service = get_user_connections_service()

        result = await connections_service.get_suggested_connections(
            user_id, limit=limit, offset=offset
        )
        logger.info(
            f"[SUGGESTED CONNECTIONS] Returned {len(result.get('suggested_connections', []))} suggestions for user {user_id}"
        )

        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting suggested connections: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get suggested connections"
        )


# =============================================================================
# USER ACTIVITY FEED ENDPOINTS
# =============================================================================


@app.get("/api/v1/users/{user_id}/activity", tags=["User Activity"])
async def get_user_activity(
    user_id: str, limit: int = MAX_ACTIVITY_ITEMS, offset: int = 0
):
    """Get user's public activity feed"""
    try:
        # Enforce maximum limit
        limit = min(limit, MAX_ACTIVITY_ITEMS)

        activity_service = get_user_activity_service()
        activity = await activity_service.get_user_activity(
            user_id, limit=limit, offset=offset
        )
        return {"success": True, "data": activity}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user activity")


@app.get("/api/v1/users/activity/feed", tags=["User Activity"])
async def get_personalized_activity_feed(
    request: Request,
    include_connections: bool = True,
    limit: int = MAX_ACTIVITY_ITEMS,
    offset: int = 0,
):
    """Get personalized activity feed including connections' activities"""
    try:
        user_id = get_current_user_id(request)
        activity_service = get_user_activity_service()

        # Enforce maximum limit
        limit = min(limit, MAX_ACTIVITY_ITEMS)

        feed = await activity_service.get_activity_feed(
            user_id, include_connections=include_connections, limit=limit, offset=offset
        )

        return {"success": True, "data": feed}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting activity feed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get activity feed")


@app.get("/api/v1/users/activity/stats", tags=["User Activity"])
async def get_activity_stats(request: Request, days: int = 30):
    """Get user's activity statistics"""
    try:
        user_id = get_current_user_id(request)
        activity_service = get_user_activity_service()

        stats = await activity_service.get_activity_stats(user_id, days=days)

        return {"success": True, "data": stats}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting activity stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get activity stats")


# =============================================================================
# =============================================================================
# USER SETTINGS ENDPOINTS
# =============================================================================


@app.get("/api/v1/users/settings", tags=["User Settings"])
async def get_user_settings(request: Request):
    """Get all user settings (notification preferences + privacy settings)"""
    try:
        user_id = get_current_user_id(request)
        settings_service = get_user_settings_service()

        settings = await settings_service.get_all_settings(user_id)

        return {"success": True, "data": settings}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user settings: {str(e)}")
        raise HTTPException(500, f"Failed to get user settings: {str(e)}")


@app.get("/api/v1/users/notification-preferences", tags=["User Settings"])
async def get_notification_preferences(request: Request):
    """Get user's notification preferences"""
    try:
        user_id = get_current_user_id(request)
        settings_service = get_user_settings_service()

        prefs = await settings_service.get_notification_preferences(user_id)

        return {"success": True, "data": prefs}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notification preferences: {str(e)}")
        raise HTTPException(500, f"Failed to get notification preferences: {str(e)}")


@app.put("/api/v1/users/notification-preferences", tags=["User Settings"])
async def update_notification_preferences(
    request: Request, preferences: Dict[str, Any]
):
    """
    Update user's notification preferences

    Example request body:
    {
        "new_follower": true,
        "replies_to_comments": true,
        "direct_messages": true,
        "new_episodes_from_followed_shows": true,
        "recommended_episodes": false,
        "upcoming_events_and_workshops": true,
        "product_updates_and_new_features": true,
        "promotions_and_partner_deals": false,
        "email_notifications": true,
        "push_notifications": true
    }
    """
    try:
        user_id = get_current_user_id(request)
        settings_service = get_user_settings_service()

        updated_prefs = await settings_service.update_notification_preferences(
            user_id, preferences
        )

        return {"success": True, "data": updated_prefs}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating notification preferences: {str(e)}")
        raise HTTPException(500, f"Failed to update notification preferences: {str(e)}")


@app.get("/api/v1/users/privacy-settings", tags=["User Settings"])
async def get_privacy_settings(request: Request):
    """Get user's privacy settings"""
    try:
        user_id = get_current_user_id(request)
        settings_service = get_user_settings_service()

        settings = await settings_service.get_privacy_settings(user_id)

        return {"success": True, "data": settings}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting privacy settings: {str(e)}")
        raise HTTPException(500, f"Failed to get privacy settings: {str(e)}")


@app.put("/api/v1/users/privacy-settings", tags=["User Settings"])
async def update_privacy_settings(request: Request, settings: Dict[str, Any]):
    """
    Update user's privacy settings

    Example request body:
    {
        "profile_visibility": true,
        "search_visibility": true,
        "show_activity_status": true
    }
    """
    try:
        user_id = get_current_user_id(request)
        settings_service = get_user_settings_service()

        updated_settings = await settings_service.update_privacy_settings(
            user_id, settings
        )

        return {"success": True, "data": updated_settings}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating privacy settings: {str(e)}")
        raise HTTPException(500, f"Failed to update privacy settings: {str(e)}")


@app.delete("/api/v1/users/account", tags=["User Settings"])
async def delete_user_account(request: Request, deletion_reason: Optional[str] = None):
    """
    Permanently delete user account and all associated data
    WARNING: This action cannot be undone

    This will delete:
    - User profile and settings
    - All posts, comments, and likes
    - All messages and conversations
    - All connections and follows
    - All notifications
    - Listening progress and podcast follows
    - Resource interactions
    - Event registrations
    - Activity logs
    - Media uploads
    - Auth account

    Query Parameters:
    - deletion_reason (optional): Reason for account deletion
    """
    try:
        user_id = get_current_user_id(request)

        # Get client IP and user agent for logging
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Import deletion service
        from account_deletion_service import get_account_deletion_service

        deletion_service = get_account_deletion_service()

        # Perform deletion
        result = await deletion_service.delete_user_account(
            user_id=user_id,
            deletion_reason=deletion_reason,
            deleted_by=None,  # Self-deletion
            ip_address=client_ip,
            user_agent=user_agent,
        )

        if not result.get("success"):
            raise HTTPException(500, result.get("error", "Failed to delete account"))

        # Build response message
        message = "Account successfully deleted"
        if result.get("auth_deletion_failed"):
            message += " (Note: Auth user deletion failed - may need manual cleanup)"

        return {
            "success": True,
            "message": message,
            "deletion_log_id": result.get("deletion_log_id"),
            "deleted_counts": result.get("deleted_counts"),
            "auth_deletion_failed": result.get("auth_deletion_failed", False),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user account: {str(e)}")
        raise HTTPException(500, f"Failed to delete user account: {str(e)}")


# GLOBAL SEARCH ENDPOINT
# =============================================================================


@app.get("/api/v1/search", tags=["Search"], response_model=GlobalSearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: Optional[int] = Query(
        None, ge=1, le=50, description="Results limit per category (max 50)"
    ),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    request: Request = None,
):
    """
    Global search across all content types with pagination: podcasts, episodes, posts, comments, messages, events, and users

    - Searches all content types in parallel with pagination support
    - Results are cached for 1 hour (configurable via SEARCH_CACHE_TTL_SECONDS)
    - Returns grouped results by content type with pre-signed URLs for all images
    - Messages search only includes conversations user participates in
    - All user avatars, post images, podcast/episode covers use pre-signed URLs for security

    Pagination:
    - Use `offset` parameter to skip results (0-indexed)
    - Use `limit` parameter to control results per category (default: 10, max: 50)
    """
    try:
        # Get current user ID
        user_id = get_current_user_id(request)

        # Perform global search with pagination
        from global_search_service import get_global_search_service

        search_service = get_global_search_service()

        results = await search_service.search_all(
            user_id=user_id, query=q, limit=limit, offset=offset
        )

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error performing global search: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


# =============================================================================
# NOTIFICATION ENDPOINTS (SSE)
# =============================================================================


@app.get("/api/v1/notifications/stream", tags=["Notifications"])
async def notification_stream(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """
    Server-Sent Events endpoint for real-time notifications.

    Keeps connection open and streams notifications as they arrive.
    Client should use EventSource API to connect.
    """
    import asyncio
    import json

    async def event_generator():
        """Generator that yields SSE formatted events"""
        # Register this connection
        queue = await notification_manager.add_connection(user_id)

        try:
            # Send initial connection success event
            yield f"event: connected\ndata: {json.dumps({'connected': True, 'timestamp': datetime.utcnow().isoformat()})}\n\n"

            # Send any unread notifications immediately
            notification_service = NotificationService()
            unread_notifications = await notification_service.get_notifications(
                user_id=user_id, limit=50, unread_only=False
            )

            if unread_notifications:
                yield f"event: initial\ndata: {json.dumps({'notifications': unread_notifications})}\n\n"

            # Keep connection alive and listen for new notifications
            while True:
                try:
                    # Wait for notification with timeout for heartbeat
                    notification = await asyncio.wait_for(queue.get(), timeout=30.0)

                    # Send notification to client
                    yield f"event: notification\ndata: {json.dumps(notification)}\n\n"

                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"

        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for user {user_id}")
        except GeneratorExit:
            # Client disconnected, this is normal
            logger.info(f"SSE connection closed by client for user {user_id}")
        except Exception as e:
            # Only log unexpected errors
            if "LocalProtocolError" not in str(type(e).__name__):
                logger.error(f"Error in SSE stream for user {user_id}: {e}")
        finally:
            # Clean up connection
            await notification_manager.remove_connection(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.get("/api/v1/notifications", tags=["Notifications"])
async def get_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user_id: str = Depends(get_current_user_from_session),
):
    """Get user's notifications with pagination"""
    try:
        notification_service = NotificationService()
        notifications = await notification_service.get_notifications(
            user_id=user_id, limit=limit, offset=offset, unread_only=unread_only
        )

        unread_count = await notification_service.get_unread_count(user_id)

        return {
            "success": True,
            "data": {
                "notifications": notifications,
                "unread_count": unread_count,
                "has_more": len(notifications) == limit,
            },
        }
    except Exception as e:
        logger.error(f"Error getting notifications for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get notifications")


@app.get("/api/v1/notifications/unread-count", tags=["Notifications"])
async def get_unread_count(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Get count of unread notifications"""
    try:
        notification_service = NotificationService()
        count = await notification_service.get_unread_count(user_id)

        return {"success": True, "data": {"unread_count": count}}
    except Exception as e:
        logger.error(f"Error getting unread count for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get unread count")


@app.post("/api/v1/notifications/{notification_id}/read", tags=["Notifications"])
async def mark_notification_read(
    notification_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Mark a notification as read"""
    try:
        notification_service = NotificationService()
        success = await notification_service.mark_as_read(notification_id, user_id)

        if not success:
            raise HTTPException(status_code=404, detail="Notification not found")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification {notification_id} as read: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to mark notification as read"
        )


@app.post("/api/v1/notifications/read-all", tags=["Notifications"])
async def mark_all_notifications_read(
    request: Request, user_id: str = Depends(get_current_user_from_session)
):
    """Mark all notifications as read"""
    try:
        notification_service = NotificationService()
        success = await notification_service.mark_all_as_read(user_id)

        if not success:
            raise HTTPException(
                status_code=500, detail="Failed to mark all notifications as read"
            )

        return {"success": True}
    except Exception as e:
        logger.error(f"Error marking all notifications as read for user {user_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to mark all notifications as read"
        )


@app.delete("/api/v1/notifications/{notification_id}", tags=["Notifications"])
async def delete_notification(
    notification_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_from_session),
):
    """Delete a notification"""
    try:
        notification_service = NotificationService()
        success = await notification_service.delete_notification(
            notification_id, user_id
        )

        if not success:
            raise HTTPException(status_code=404, detail="Notification not found")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notification {notification_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete notification")


# =============================================================================
# STRIPE & SUBSCRIPTION ENDPOINTS
# =============================================================================

@app.post("/api/v1/stripe/create-checkout-session", response_model=CreateCheckoutSessionResponse, tags=["Stripe"])
async def create_checkout_session(
    request_data: CreateCheckoutSessionRequest,
    request: Request
):
    """
    Create a Stripe Checkout Session for subscription.
    User must be authenticated.
    """
    try:
        # Get authenticated user
        user_id = get_current_user_id(request)

        # Get user email from Supabase
        user_data = supabase_client.service_client.auth.admin.get_user_by_id(user_id)
        if not user_data or not user_data.user:
            raise HTTPException(status_code=404, detail="User not found")

        email = user_data.user.email
        name = user_data.user.user_metadata.get("name") if user_data.user.user_metadata else None

        logger.info(f"Creating checkout session for user {user_id}, plan: {request_data.plan}")

        # Initialize services
        from stripe_service import StripeService
        from subscription_service import SubscriptionService

        stripe_service = StripeService()
        subscription_service = SubscriptionService()

        # Get or create Stripe customer
        stripe_customer_id = subscription_service.get_stripe_customer_id(user_id)

        if not stripe_customer_id:
            # Create new Stripe customer
            stripe_customer_id = stripe_service.get_or_create_customer(user_id, email, name)

            if not stripe_customer_id:
                raise HTTPException(status_code=500, detail="Failed to create Stripe customer")

            # Save to database
            subscription_service.get_or_create_stripe_customer(user_id, stripe_customer_id, email)

        # Get price ID and mode based on plan
        if request_data.plan == "pro_monthly":
            price_id = stripe_service.pro_monthly_price_id
            mode = "subscription"
        elif request_data.plan == "lifetime":
            price_id = stripe_service.lifetime_price_id
            mode = "payment"
        else:
            raise HTTPException(status_code=400, detail="Invalid plan type")

        if not price_id:
            raise HTTPException(status_code=500, detail=f"Stripe price ID not configured for {request_data.plan} plan")

        # Create checkout session (uses env var URLs)
        session = stripe_service.create_checkout_session(
            customer_id=stripe_customer_id,
            price_id=price_id,
            user_id=user_id,
            mode=mode
        )

        if not session:
            raise HTTPException(status_code=500, detail="Failed to create checkout session")

        logger.info(f"✅ Created checkout session {session['session_id']} for user {user_id}")

        return CreateCheckoutSessionResponse(
            success=True,
            session_id=session["session_id"],
            url=session["url"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating checkout session: {str(e)}", exc_info=True)
        return CreateCheckoutSessionResponse(
            success=False,
            error="Failed to create checkout session"
        )


@app.post("/api/v1/stripe/create-portal-session", response_model=CreatePortalSessionResponse, tags=["Stripe"])
async def create_portal_session(
    request_data: CreatePortalSessionRequest,
    request: Request
):
    """
    Create a Stripe Customer Portal session for subscription management.
    User must be authenticated and have a Stripe customer ID.
    """
    try:
        # Get authenticated user
        user_id = get_current_user_id(request)

        logger.info(f"Creating portal session for user {user_id}")

        # Initialize services
        from stripe_service import StripeService
        from subscription_service import SubscriptionService

        stripe_service = StripeService()
        subscription_service = SubscriptionService()

        # Get Stripe customer ID
        stripe_customer_id = subscription_service.get_stripe_customer_id(user_id)

        if not stripe_customer_id:
            raise HTTPException(status_code=404, detail="No Stripe customer found for user")

        # Create portal session
        portal_url = stripe_service.create_customer_portal_session(
            customer_id=stripe_customer_id,
            return_url=request_data.return_url
        )

        if not portal_url:
            raise HTTPException(status_code=500, detail="Failed to create portal session")

        logger.info(f"✅ Created portal session for user {user_id}")

        return CreatePortalSessionResponse(
            success=True,
            url=portal_url
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating portal session: {str(e)}", exc_info=True)
        return CreatePortalSessionResponse(
            success=False,
            error="Failed to create portal session"
        )


@app.post("/api/v1/stripe/webhook", tags=["Stripe"])
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.
    This endpoint receives events from Stripe and updates the database accordingly.
    """
    try:
        # Get raw body and signature
        payload = await request.body()
        signature = request.headers.get("stripe-signature")

        if not signature:
            logger.warning("❌ Stripe webhook: Missing signature")
            raise HTTPException(status_code=400, detail="Missing stripe-signature header")

        # Initialize services
        from stripe_service import StripeService
        from subscription_service import SubscriptionService

        stripe_service = StripeService()
        subscription_service = SubscriptionService()

        # Verify webhook signature
        event = stripe_service.verify_webhook_signature(payload, signature)

        if not event:
            logger.warning("❌ Stripe webhook: Invalid signature")
            raise HTTPException(status_code=400, detail="Invalid signature")

        event_type = event["type"]
        logger.info(f"📧 Received Stripe webhook: {event_type}")

        # Handle different event types
        if event_type == "checkout.session.completed":
            # Payment successful - create subscription record
            session = event["data"]["object"]
            subscription_id = session.get("subscription")
            customer_id = session.get("customer")
            user_id = session.get("metadata", {}).get("user_id")

            if subscription_id and user_id:
                logger.info(f"Checkout completed: subscription {subscription_id} for user {user_id}")

                # Get full subscription details from Stripe
                subscription_data = stripe_service.retrieve_subscription(subscription_id)

                if subscription_data:
                    # Create subscription record in database
                    db_subscription = {
                        "user_id": user_id,
                        "stripe_subscription_id": subscription_data["id"],
                        "stripe_customer_id": subscription_data["customer"],
                        "status": subscription_data["status"],
                        "plan_id": subscription_data["plan_id"],
                        "current_period_start": subscription_data["current_period_start"].isoformat(),
                        "current_period_end": subscription_data["current_period_end"].isoformat(),
                        "cancel_at_period_end": subscription_data["cancel_at_period_end"],
                        "canceled_at": subscription_data["canceled_at"].isoformat() if subscription_data["canceled_at"] else None,
                        "trial_start": subscription_data["trial_start"].isoformat() if subscription_data["trial_start"] else None,
                        "trial_end": subscription_data["trial_end"].isoformat() if subscription_data["trial_end"] else None
                    }

                    result = subscription_service.create_subscription(db_subscription)
                    if result["success"]:
                        logger.info(f"✅ Created subscription record for user {user_id}")
                    else:
                        logger.error(f"❌ Failed to create subscription record: {result.get('error')}")

        elif event_type == "customer.subscription.created":
            # New subscription created
            subscription = event["data"]["object"]
            subscription_id = subscription["id"]
            user_id = subscription.get("metadata", {}).get("user_id")

            # Get user_id from customer if not in metadata
            if not user_id:
                customer_id = subscription.get("customer")
                user_id = subscription_service.get_user_by_stripe_customer_id(customer_id)

            if user_id:
                logger.info(f"Subscription created: {subscription_id} for user {user_id}")
                # Subscription will be created by checkout.session.completed

        elif event_type == "customer.subscription.updated":
            # Subscription updated (plan change, cancellation scheduled, etc.)
            subscription = event["data"]["object"]
            subscription_id = subscription["id"]

            logger.info(f"Subscription updated: {subscription_id}")

            update_data = {
                "status": subscription["status"],
                "current_period_start": datetime.fromtimestamp(subscription["current_period_start"], tz=timezone.utc).isoformat(),
                "current_period_end": datetime.fromtimestamp(subscription["current_period_end"], tz=timezone.utc).isoformat(),
                "cancel_at_period_end": subscription["cancel_at_period_end"],
                "canceled_at": datetime.fromtimestamp(subscription["canceled_at"], tz=timezone.utc).isoformat() if subscription.get("canceled_at") else None
            }

            result = subscription_service.update_subscription(subscription_id, update_data)
            if result["success"]:
                logger.info(f"✅ Updated subscription {subscription_id}")
            else:
                logger.error(f"❌ Failed to update subscription: {result.get('error')}")

        elif event_type == "customer.subscription.deleted":
            # Subscription canceled/ended
            subscription = event["data"]["object"]
            subscription_id = subscription["id"]

            logger.info(f"Subscription deleted: {subscription_id}")

            result = subscription_service.delete_subscription(subscription_id)
            if result["success"]:
                logger.info(f"✅ Marked subscription {subscription_id} as canceled")
            else:
                logger.error(f"❌ Failed to delete subscription: {result.get('error')}")

        elif event_type == "invoice.paid":
            # Successful payment - update billing period
            invoice = event["data"]["object"]
            subscription_id = invoice.get("subscription")

            if subscription_id:
                logger.info(f"Invoice paid for subscription {subscription_id}")

                # Get updated subscription details
                subscription_data = stripe_service.retrieve_subscription(subscription_id)

                if subscription_data:
                    update_data = {
                        "status": subscription_data["status"],
                        "current_period_start": subscription_data["current_period_start"].isoformat(),
                        "current_period_end": subscription_data["current_period_end"].isoformat()
                    }

                    result = subscription_service.update_subscription(subscription_id, update_data)
                    if result["success"]:
                        logger.info(f"✅ Updated billing period for subscription {subscription_id}")

        elif event_type == "invoice.payment_failed":
            # Payment failed - mark as past_due
            invoice = event["data"]["object"]
            subscription_id = invoice.get("subscription")

            if subscription_id:
                logger.warning(f"⚠️  Payment failed for subscription {subscription_id}")

                update_data = {
                    "status": "past_due"
                }

                result = subscription_service.update_subscription(subscription_id, update_data)
                if result["success"]:
                    logger.info(f"✅ Marked subscription {subscription_id} as past_due")

        elif event_type == "payment_intent.succeeded":
            # One-time payment succeeded (for lifetime membership)
            payment_intent = event["data"]["object"]
            payment_intent_id = payment_intent["id"]
            customer_id = payment_intent.get("customer")
            user_id = payment_intent.get("metadata", {}).get("user_id")
            plan_type = payment_intent.get("metadata", {}).get("plan_type")

            if plan_type == "lifetime" and user_id:
                logger.info(f"Lifetime payment succeeded for user {user_id}")

                # Get payment intent details
                payment_data = stripe_service.retrieve_payment_intent(payment_intent_id)

                if payment_data:
                    # Create lifetime subscription record
                    db_subscription = {
                        "user_id": user_id,
                        "stripe_customer_id": customer_id,
                        "payment_intent_id": payment_intent_id,
                        "status": "lifetime_active",
                        "plan_id": "lifetime",
                        "subscription_type": "lifetime",
                        "lifetime_access": True,
                        "current_period_start": payment_data["created"].isoformat(),
                        "current_period_end": None,  # No expiry for lifetime
                        "stripe_subscription_id": f"lifetime_{payment_intent_id}"  # Placeholder for unique constraint
                    }

                    result = subscription_service.create_subscription(db_subscription)
                    if result["success"]:
                        logger.info(f"✅ Created lifetime subscription for user {user_id}")
                    else:
                        logger.error(f"❌ Failed to create lifetime subscription: {result.get('error')}")

        else:
            logger.info(f"Unhandled webhook event type: {event_type}")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {str(e)}", exc_info=True)
        # Return 200 to avoid Stripe retries for invalid events
        return {"success": False, "error": str(e)}


@app.get("/api/v1/subscription/status", response_model=SubscriptionStatusResponse, tags=["Subscription"])
async def get_subscription_status(request: Request):
    """
    Get current user's subscription status.
    User must be authenticated.
    """
    try:
        # Get authenticated user
        user_id = get_current_user_id(request)

        # Initialize service
        from subscription_service import SubscriptionService
        subscription_service = SubscriptionService()

        # Get user's subscription
        result = subscription_service.get_user_subscription(user_id)

        if not result["success"]:
            raise HTTPException(status_code=500, detail="Failed to get subscription status")

        subscription_data = result.get("data")

        if not subscription_data:
            # No subscription
            return SubscriptionStatusResponse(
                success=True,
                subscription=SubscriptionStatus(has_subscription=False)
            )

        # Parse dates
        current_period_end = datetime.fromisoformat(subscription_data["current_period_end"].replace("Z", "+00:00")) if subscription_data.get("current_period_end") else None
        trial_end = datetime.fromisoformat(subscription_data["trial_end"].replace("Z", "+00:00")) if subscription_data.get("trial_end") else None

        return SubscriptionStatusResponse(
            success=True,
            subscription=SubscriptionStatus(
                has_subscription=True,
                subscription_type=subscription_data.get("subscription_type", "recurring"),
                status=subscription_data["status"],
                plan_id=subscription_data["plan_id"],
                current_period_end=current_period_end,
                cancel_at_period_end=subscription_data.get("cancel_at_period_end", False),
                trial_end=trial_end,
                lifetime_access=subscription_data.get("lifetime_access", False)
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting subscription status: {str(e)}", exc_info=True)
        return SubscriptionStatusResponse(
            success=False,
            error="Failed to get subscription status"
        )


# =============================================================================
# SYSTEM ENDPOINTS
# =============================================================================


@app.get("/api/v1/health", tags=["System"])
async def health_check():
    """Health check endpoint with scheduler info"""
    scheduler_running = scheduler_service.is_running if scheduler_service else False
    return {"status": "healthy", "scheduler_running": scheduler_running}


@app.get("/api/v1/my-ip", tags=["System"])
async def get_my_ip(request: Request):
    """Get the client IP address as seen by the server"""
    # Same IP detection logic as DocsIPFilterMiddleware
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "").strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    logger.info(f"IP check requested from: {client_ip}")

    return {
        "your_ip": client_ip,
        "headers": {
            "X-Forwarded-For": request.headers.get("X-Forwarded-For"),
            "X-Real-IP": request.headers.get("X-Real-IP"),
            "Host": request.headers.get("Host"),
        },
        "client_info": {
            "host": request.client.host if request.client else None,
            "port": request.client.port if request.client else None,
        },
    }


# @app.post("/api/v1/admin/sync-failed-waitlist", tags=["Admin"])
# @limiter.limit("5/minute")
# async def manually_sync_failed_waitlist(request: Request, _: None = Depends(require_localhost)):
#     """Manually trigger sync of failed waitlist entries to Customer.io"""
#     from background_tasks import sync_failed_waitlist_entries
#
#     try:
#         result = await sync_failed_waitlist_entries()
#         return result
#     except Exception as e:
#         logger.error(f"Manual waitlist sync error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@app.post("/api/v1/debug/customerio", tags=["Debug"])
async def debug_customerio():
    """Debug Customer.io configuration and connection"""
    try:
        return {
            "config": {
                "api_key_set": bool(customerio_client.api_key),
                "api_key_prefix": customerio_client.api_key[:10] + "..."
                if customerio_client.api_key
                else "None",
                "region": customerio_client.region,
                "transactional_url": customerio_client.transactional_url,
                "message_id": os.getenv(
                    "CUSTOMERIO_SIGNUP_CONFIRMATION_MESSAGE_ID", "2"
                ),
            },
            "instructions": "Set CUSTOMERIO_SIGNUP_CONFIRMATION_MESSAGE_ID environment variable to your actual message ID from Customer.io",
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/v1/grant-application", response_model=CreateGrantApplicationResponse, tags=["Grant Application"])
@limiter.limit("5/hour")
async def create_grant_application(
    grant_application: CreateGrantApplicationRequest,
    request: Request,
    supabase: SupabaseClient = Depends(get_supabase_client) # Changed dependency
):
    """
    Create a new grant application
    """
    try:
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, grant_application.email):
            raise HTTPException(status_code=400, detail="Invalid email format")

        supabase_result = supabase_client.service_client.table("grant_applications").select("*").eq("email",
            grant_application.email).execute()

        if supabase_result.data:
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "message": "Email already exists in grant application",
                    },
                )

        response = supabase.create_grant_application(grant_application.model_dump()) 
        new_application = None
        if response.get("success"):
            new_application = response.get("data")
        
            print(new_application)
            # Log the successful application
            logger.info(f"New grant application created for {grant_application.email}: {grant_application.podcast_title}")
        # Return response using the response model
            return CreateGrantApplicationResponse(**new_application)

    except HTTPException:
        # Re-raise HTTP exceptions as they are
        raise
    except Exception as e:
        logger.error(f"Error creating grant application: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error occurred while processing your application")


# @app.post("/api/v1/admin/categorize-podcasts", tags=["Admin"])
# @limiter.limit("5/minute")
# async def manually_categorize_podcasts(request: Request, _: None = Depends(require_localhost), batch_size: int = 5):
#     """Manually trigger podcast categorization using Gemini AI"""
#     from background_tasks import categorize_uncategorized_podcasts
#
#     try:
#         # Note: The batch_size parameter here won't affect the background task
#         # which has its own hardcoded batch size. To make it configurable,
#         # we'd need to modify the background task function.
#         result = await categorize_uncategorized_podcasts()
#         return result
#     except Exception as e:
#         logger.error(f"Manual podcast categorization error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Categorization failed: {str(e)}")

app.mount("/admin", admin_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=True)
