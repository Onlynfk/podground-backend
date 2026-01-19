from typing import Any, Sequence
from asgiref.sync import sync_to_async
from django.http.request import HttpRequest
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)
from fastapi import UploadFile
from tempfile import SpooledTemporaryFile
import base64 as b64
import io
from django.contrib.postgres.fields import ArrayField
from django.db import models
import uuid
from fastadmin import (
    DjangoInlineModelAdmin,
    DjangoModelAdmin,
    ModelAdmin,
    register,
)
import article_content_service
from context import get_current_user_id
from decouple import config
from fastadmin import (
    DashboardWidgetAdmin,
    DashboardWidgetType,
    WidgetType,
    register_widget,
)
from django.db import connection
import datetime
from django.contrib import admin

from auth_dependencies import get_current_user_from_request
from media_service import MediaService
from article_content_service import ArticleContentService

media_service = MediaService()
article_content_service = ArticleContentService()


# general models needed
class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Admin(AbstractBaseUser):
    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    email = models.EmailField(unique=True)
    is_staff = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_users"
        managed = False

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    host_user_id = models.UUIDField(null=True, blank=True)

    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)

    location = models.TextField(null=True, blank=True)
    is_online = models.BooleanField(default=False)

    url = models.URLField(null=True, blank=True)
    image_url = models.URLField(null=True, blank=True)

    is_featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    required_plan = models.CharField(max_length=50, default="free")

    is_premium = models.BooleanField(default=False)

    event_date = models.DateTimeField(null=True, blank=True)

    category = models.CharField(max_length=50, default="general")

    event_type = models.CharField(max_length=50, default="webinar")

    is_paid = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    meeting_url = models.URLField(null=True, blank=True)
    replay_video_url = models.URLField(null=True, blank=True)

    tags = ArrayField(
        base_field=models.CharField(max_length=100), default=list, blank=True
    )

    timezone = models.CharField(max_length=50, default="UTC")

    status = models.CharField(max_length=50, default="scheduled")

    updated_at = models.DateTimeField(auto_now=True)

    host_name = models.CharField(max_length=255, default="PodGround")

    calget_link = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "events"

    def __str__(self):
        return self.title


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "users"
        managed = False

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.first_name or ''} {self.last_name or ''} <{self.email}>".strip()


class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, db_column="user_id"
    )
    bio = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    avatar_url = models.URLField(blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profiles"
        managed = False

    def __str__(self):
        return f"Profile of {self.user.email}"


class Podcast(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    language = models.CharField(max_length=10, default="en")
    image_url = models.URLField(blank=True, null=True)
    explicit_content = models.BooleanField(default=False)
    total_episodes = models.IntegerField(default=0)
    is_featured = models.BooleanField(
        default=False
    )  # inferred from your "Published status"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "podcasts"
        managed = False

    def __str__(self):
        return self.title


class Episode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    podcast = models.ForeignKey(
        Podcast, on_delete=models.CASCADE, db_column="podcast_id"
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    audio_url = models.URLField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    episode_number = models.IntegerField()
    duration_seconds = models.IntegerField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "episodes"
        managed = False

    def __str__(self):
        return f"{self.podcast.title} – {self.title}"


class Post(models.Model):
    POST_TYPES = [
        ("text", "Text"),
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("poll", "Poll"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id"
    )
    content = models.TextField(blank=True, null=True)
    post_type = models.CharField(
        max_length=20, choices=POST_TYPES, default="text"
    )
    podcast_episode_url = models.URLField(blank=True, null=True)
    is_published = models.BooleanField(default=True)
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "posts"
        managed = False

    def __str__(self):
        return f"Post by {self.user.email} ({self.post_type})"


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, db_column="post_id"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id"
    )
    content = models.TextField()
    parent_comment = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="parent_comment_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "post_comments"
        managed = False

    def __str__(self):
        return f"Comment by {self.user.email}: {self.content[:50]}"


class Conversation(models.Model):
    CONVERSATION_TYPES = [
        ("direct", "Direct"),
        ("group", "Group"),
        ("podcast", "Podcast"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, blank=True, null=True)
    conversation_type = models.CharField(
        max_length=20, choices=CONVERSATION_TYPES, default="direct"
    )
    podcast = models.ForeignKey(
        Podcast,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="podcast_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        managed = False


class Message(models.Model):
    MESSAGE_TYPES = [
        ("text", "Text"),
        ("voice", "Voice"),
        ("attachment", "Attachment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, db_column="conversation_id"
    )
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="sender_id"
    )
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPES, default="text"
    )
    attachment_url = models.URLField(null=True)
    reply_to_message = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True
    )
    content = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    @property
    def sender_name(self):
        return self.sender.full_name

    class Meta:
        db_table = "messages"
        managed = False

    def __str__(self):
        return f"Msg from {self.sender.email} in {self.conversation.id}"


class Resource(models.Model):
    RESOURCE_TYPES = [
        ("article", "Article"),
        ("video", "Video"),
        ("guide", "Guide"),
        ("tool", "Tool"),
        ("template", "Template"),
        ("course", "Course"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    content = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    url = models.URLField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    required_plan = models.CharField(max_length=50, default="free")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_blog = models.BooleanField(default=False)

    class Meta:
        db_table = "resources"
        managed = False

    def __str__(self):
        return self.title


class SubscriptionPlan(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    price_monthly = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )
    price_yearly = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "subscription_plans"
        managed = False


class UserSubscription(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, db_column="user_id"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.CASCADE, db_column="plan_id"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(blank=True, null=True)
    stripe_subscription_id = models.CharField(
        max_length=255, blank=True, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_subscriptions"
        managed = False

    def __str__(self):
        return f"{self.user.email} – {self.plan.name} ({self.status})"


# fastadmin models
ADMIN_USERNAME = "admin@example.com"
ADMIN_PASSWORD = "supersecurepassword"  # hashed preferably


@register(Admin)
class AdminUser(DjangoModelAdmin):
    exclude = ("password",)

    def authenticate(self, username, password):
        user = Admin.objects.filter(email=username).first()
        if not user:
            return None
        if not user.check_password(password):
            return None
        print("authenticated_user", user.id)
        return user.id


class UserProfileAdminInline(DjangoInlineModelAdmin):
    exclude = (
        "hash_password",
        "last_login",
    )
    list_display = ("id", "first_name", "last_name", "email", "is_active")
    list_display_links = ("id", "username")
    list_filter = ("id", "username", "is_superuser", "is_active")
    search_fields = ("username",)

    model = UserProfile


@register(User)
class UserAdmin(DjangoModelAdmin):
    search_fields = (
        "id",
        "email",
        "first_name",
        "last_name",
    )
    list_display = ("id", "first_name", "last_name", "email", "is_active")
    inlines = (UserProfileAdminInline,)
    readonly_fields = (
        "first_name",
        "last_name",
        "email",
    )


class EpisodesInlineAdmin(DjangoInlineModelAdmin):
    model = Episode

    list_display = (
        "title",
        "published_at",
        "duration_seconds",
        "episode_number",
    )


@register(Podcast)
class PodcastAdmin(DjangoModelAdmin):
    search_fields = ("title",)
    list_display = (
        "title",
        "id",
        "total_episodes",
    )
    list_filter = (
        "language",
        "total_episodes",
        "is_active",
    )

    inlines = (EpisodesInlineAdmin,)


@register(Episode)
class EpisodesAdmin(DjangoModelAdmin):
    list_display = (
        "title",
        "description",
        "podcast.title",
        "podcast",
        "podcast_title",
        "published_at",
    )
    search_fields = (
        "podcast__title",
        "description",
        "title",
    )

    list_display_links: Sequence[str] = ("title",)
    list_display_widths = {"id": "50px"}

    list_filter = ("podcast__title",)


class PostCommentInline(DjangoInlineModelAdmin):
    model = Comment
    list_display = ("user", "created_at")


@register(Post)
class PostAdmin(DjangoModelAdmin):
    list_display = (
        "id",
        "user_email",
        "post_type",
        "comment_count",
        "podcast_episode_url",
        "is_published",
        "created_at",
    )
    list_filter = ("post_type", "is_published", "created_at")
    search_fields = ("content", "user__email")
    list_display_links = ("id",)

    inlines = (PostCommentInline,)

    # Optional: display user email instead of ID
    def user_email(self, obj):
        return obj.user.email

    user_email.short_description = "User"
    user_email.admin_order_field = "user__email"


@register(Resource)
class ResourceAdmin(DjangoModelAdmin):
    list_display = (
        "title",
        "description",
        "is_premium",
    )

    list_display_links = ("title",)
    formfield_overrides = {
        "image_url": (WidgetType.Upload, {"required": False}),
        "url": (WidgetType.Upload, {"required": False}),
    }

    def extract_base64(self, data: str) -> tuple[str, str | None]:
        """
        Returns (base64_payload, content_type)
        """
        if data.startswith("data:"):
            header, payload = data.split(",", 1)
            # header looks like: data:image/png;base64
            content_type = header.split(";")[0].replace("data:", "")
            return payload, content_type
        return data, None

    def decode_data_url(self, data_url: str) -> bytes:
        # Split by comma, the second part is the actual Base64
        if "," in data_url:
            header, encoded = data_url.split(",", 1)
        else:
            encoded = data_url

        # Fix padding if necessary
        missing_padding = len(encoded) % 4
        if missing_padding:
            encoded += "=" * (4 - missing_padding)

        return b64.b64decode(encoded)

    async def save_model(
        self, id: uuid.UUID | Any | None, payload: dict
    ) -> Any:
        """This method is used to save orm/db model object.

        :params id: an id of object.
        :params payload: a dict of payload.
        :return: An object.
        """
        print("this is the payload: ", payload)
        title = getattr(self.model_cls, "title", None)
        is_blog = getattr(self.model_cls, "is_blog", None)

        content = payload.get("content", "")
        print(title, is_blog)

        if content and len(content) == 0:
            await article_content_service.upload_article_content(
                title=title,
                resource_id=self.model_cls.id,
                author="The PodGround Team" if is_blog else "",
                content=content,
            )
        elif content and len(content) > 0:
            await article_content_service.update_article_content(
                title=title,
                resource_id=self.model_cls.id,
                author="The PodGround Team",
                content=content,
            )
        await super().save_model(id, payload)

    async def orm_save_upload_field(
        self, obj: Any, field: str, base64: str
    ) -> None:
        if not base64:
            return
        if base64.startswith("http://") or base64.startswith("https://"):
            setattr(obj, field, base64)
            await sync_to_async(obj.save)(update_fields=[field])
            return
        user_id = get_current_user_id()
        if not user_id:
            raise RuntimeError("User context missing")
        print("this is the user id", user_id)
        rb = self.decode_data_url(base64)
        # get_current_user_from_request()

        temp_file = SpooledTemporaryFile()
        temp_file.write(rb)
        temp_file.seek(0)
        upload_file = UploadFile(
            filename=f"{field}.jpg",  # choose dynamically if needed
            file=temp_file,
        )

        media_response = await media_service.upload_media_files(
            [upload_file], "aa80431a-5595-4d6c-aa5d-8fc93a87af82"
        )
        if media_response:
            media = media_response.get("media", None)
            if media:
                file_url = media[0].get("url", None)
                setattr(obj, field, file_url)
                await sync_to_async(obj.save)(update_fields=[field])


@register(Comment)
class CommentAdmin(DjangoModelAdmin):
    list_display = ("post_user", "content")

    @admin.display(description="Post User")
    def post_user(self, obj):
        print(obj, obj.post)
        return "User"


@register(Message)
class MessagesAdmin(DjangoModelAdmin):
    list_display = (
        "content",
        "sender_full_name",
    )


class UserSubscriptionAdmin(DjangoInlineModelAdmin):
    list_display = ("user", "plan", "status", "starts_at", "ends_at")

    model = UserSubscription


@register(SubscriptionPlan)
class SubscriptionPlanAdmin(DjangoModelAdmin):
    list_display = ("name", "display_name", "is_active")
    inlines = (UserSubscriptionAdmin,)


@register(Event)
class EventsAdmin(DjangoModelAdmin):
    list_display = (
        "title",
        "location",
        "is_featured",
        "start_date",
        "host_user_id",
    )


####


# @register_widget
