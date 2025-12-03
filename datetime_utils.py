"""
Datetime utilities for converting and formatting timestamps
All API responses should use Central Time (CST/CDT) with MM/DD/YYYY format
"""

import logging
from datetime import datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Central Time zone (handles DST automatically)
CENTRAL_TZ = ZoneInfo("America/Chicago")
UTC_TZ = ZoneInfo("UTC")


def format_datetime_central(
    dt: Optional[Union[str, datetime]],
    include_timezone: bool = False
) -> Optional[str]:
    """
    Convert a datetime to Central Time and format as MM/DD/YYYY h:mm AM/PM

    Args:
        dt: Datetime object or ISO format string (assumes UTC if no timezone)
        include_timezone: Whether to append CST/CDT suffix (default: False)

    Returns:
        Formatted datetime string or None if input is None/invalid

    Examples:
        "01/15/2025 2:30 PM"
        "07/04/2025 10:00 AM"
    """
    if dt is None:
        return None

    try:
        # Parse string to datetime if needed
        if isinstance(dt, str):
            # Handle ISO format strings
            dt_str = dt.replace('Z', '+00:00')

            # Try parsing with timezone
            try:
                if '+' in dt_str or '-' in dt_str[10:]:  # Has timezone offset
                    dt_obj = datetime.fromisoformat(dt_str)
                else:
                    # No timezone - assume UTC
                    dt_obj = datetime.fromisoformat(dt_str).replace(tzinfo=UTC_TZ)
            except ValueError:
                # Fallback for other formats
                dt_obj = datetime.fromisoformat(dt_str.split('.')[0]).replace(tzinfo=UTC_TZ)
        else:
            dt_obj = dt

        # Ensure datetime has timezone info (assume UTC if naive)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=UTC_TZ)

        # Convert to Central Time
        central_dt = dt_obj.astimezone(CENTRAL_TZ)

        # Format as MM/DD/YYYY h:mm AM/PM
        formatted = central_dt.strftime("%m/%d/%Y %I:%M %p")

        # Remove leading zero from hour (01:30 PM -> 1:30 PM)
        if formatted[11] == '0':
            formatted = formatted[:11] + formatted[12:]

        if include_timezone:
            # Determine if DST is in effect (CST vs CDT)
            tz_abbr = central_dt.strftime("%Z")  # Returns 'CST' or 'CDT'
            formatted = f"{formatted} {tz_abbr}"

        return formatted

    except Exception as e:
        logger.warning(f"Failed to format datetime {dt}: {str(e)}")
        # Return original value as string if conversion fails
        return str(dt) if dt else None


def format_datetime_fields(
    data: dict,
    fields: list[str],
    include_timezone: bool = True
) -> dict:
    """
    Format multiple datetime fields in a dictionary

    Args:
        data: Dictionary containing datetime fields
        fields: List of field names to format
        include_timezone: Whether to append CST/CDT suffix

    Returns:
        Dictionary with formatted datetime fields
    """
    if not data:
        return data

    result = data.copy()
    for field in fields:
        if field in result and result[field] is not None:
            result[field] = format_datetime_central(result[field], include_timezone)

    return result


def format_datetime_in_list(
    items: list[dict],
    fields: list[str],
    include_timezone: bool = True
) -> list[dict]:
    """
    Format datetime fields for a list of dictionaries

    Args:
        items: List of dictionaries containing datetime fields
        fields: List of field names to format
        include_timezone: Whether to append CST/CDT suffix

    Returns:
        List of dictionaries with formatted datetime fields
    """
    if not items:
        return items

    return [format_datetime_fields(item, fields, include_timezone) for item in items]


# Common datetime field groups for different entities
DATETIME_FIELDS = {
    "post": ["created_at", "updated_at"],
    "comment": ["created_at", "updated_at"],
    "message": ["created_at", "edited_at"],
    "notification": ["created_at", "read_at"],
    "user_profile": ["created_at", "updated_at"],
    "connection": ["created_at", "accepted_at"],
    "conversation": ["created_at", "updated_at"],
    "event": ["event_date", "start_date", "end_date", "created_at", "registration_deadline"],
    "episode": ["published_at", "pub_date", "created_at"],
    "podcast": ["created_at", "updated_at", "last_episode_date"],
    "podcast_follow": ["followed_at"],
    "listening_progress": ["started_at", "last_played_at", "completed_at"],
}


def format_post(post: dict) -> dict:
    """Format datetime fields in a post object"""
    return format_datetime_fields(post, DATETIME_FIELDS["post"])


def format_comment(comment: dict) -> dict:
    """Format datetime fields in a comment object"""
    return format_datetime_fields(comment, DATETIME_FIELDS["comment"])


def format_message(message: dict) -> dict:
    """Format datetime fields in a message object"""
    return format_datetime_fields(message, DATETIME_FIELDS["message"])


def format_notification(notification: dict) -> dict:
    """Format datetime fields in a notification object"""
    return format_datetime_fields(notification, DATETIME_FIELDS["notification"])


def format_conversation(conversation: dict) -> dict:
    """Format datetime fields in a conversation object"""
    return format_datetime_fields(conversation, DATETIME_FIELDS["conversation"])


def format_episode(episode: dict) -> dict:
    """Format datetime fields in an episode object"""
    return format_datetime_fields(episode, DATETIME_FIELDS["episode"])


def format_event(event: dict) -> dict:
    """Format datetime fields in an event object"""
    return format_datetime_fields(event, DATETIME_FIELDS["event"])
