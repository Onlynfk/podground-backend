"""
Events Service - Comprehensive event management system
Handles events, registrations, calendar integration, and attendee management
"""

import os
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import logging
from ics import Calendar, Event as ICSEvent
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

from supabase_client import SupabaseClient
from access_control import get_user_subscription_status

logger = logging.getLogger(__name__)

class EventsService:
    """Service for managing events, registrations, and attendee interactions"""
    
    def __init__(self):
        self.supabase_client = SupabaseClient()
        self.supabase = self.supabase_client.service_client
    
    async def get_events(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,  # 'upcoming', 'past', 'all'
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        is_paid: Optional[bool] = None,
        search: Optional[str] = None,
        host_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get events with comprehensive filtering"""
        try:
            # Build query
            query = self.supabase.table('events').select('*')
            
            # Filter by event timing
            now = datetime.now(timezone.utc).isoformat()
            if event_type == 'upcoming':
                query = query.gte('event_date', now).eq('status', 'scheduled')
            elif event_type == 'past':
                query = query.lt('event_date', now)
            
            # Apply other filters
            if category:
                query = query.eq('category', category)
            
            if is_paid is not None:
                query = query.eq('is_paid', is_paid)
            
            if host_id:
                query = query.eq('host_user_id', host_id)
            
            # Search in title and description
            if search:
                query = query.or_(f'title.ilike.%{search}%,description.ilike.%{search}%')
            
            # Order by event date (upcoming first)
            query = query.order('event_date', desc=False)
            
            # Apply pagination
            query = query.range(offset, offset + limit - 1)
            
            response = query.execute()
            
            if response.data:
                events = response.data
                
                # Enrich events with user registration status if user_id provided
                if user_id:
                    events = await self._enrich_events_with_user_data(events, user_id)
                
                # Remove unwanted fields from all events
                events = self._clean_event_responses(events)
                
                return {
                    'success': True,
                    'data': {
                        'events': events,
                        'total_count': len(events),
                        'has_more': len(events) == limit
                    }
                }
            
            return {
                'success': True,
                'data': {
                    'events': [],
                    'total_count': 0,
                    'has_more': False
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting events: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def get_event_by_id(self, event_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get single event with detailed information"""
        try:
            response = self.supabase.table('events').select('*').eq('id', event_id).execute()
            
            if response.data:
                event = response.data[0]
                
                # Enrich with user registration status if user_id provided
                if user_id:
                    enriched_events = await self._enrich_events_with_user_data([event], user_id)
                    event = enriched_events[0] if enriched_events else event
                
                # Remove unwanted fields from the event
                event = self._clean_event_response(event)
                
                return {'success': True, 'data': event}
            else:
                return {'success': False, 'error': 'Event not found'}
                
        except Exception as e:
            logger.error(f"Error getting event {event_id}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def create_event(
        self,
        event_data: Dict[str, Any],
        host_user_id: Optional[str] = None  # Optional for backward compatibility
    ) -> Dict[str, Any]:
        """Create a new event (PodGround platform event)"""
        try:
            # Generate event ID
            event_id = str(uuid.uuid4())
            
            # Prepare event record
            event_record = {
                'id': event_id,
                'host_user_id': None,  # All events are PodGround events
                'host_name': event_data.get('host_name', 'PodGround'),
                'title': event_data['title'],
                'description': event_data['description'],
                'event_date': event_data['event_date'],
                'start_date': event_data['event_date'],  # For backward compatibility
                'location': event_data.get('location', 'Virtual'),
                'category': event_data.get('category', 'general'),
                'event_type': event_data.get('event_type', 'webinar'),
                'max_attendees': event_data.get('max_attendees', 100),
                'is_paid': event_data.get('is_paid', False),
                'price': event_data.get('price', 0.00),
                'image_url': event_data.get('image_url'),
                'meeting_url': event_data.get('meeting_url'),
                'tags': event_data.get('tags', []),
                'timezone': event_data.get('timezone', 'UTC'),
                'registration_deadline': event_data.get('registration_deadline'),
                'allow_waitlist': event_data.get('allow_waitlist', True),
                'status': 'scheduled',
                'calget_link': event_data.get('calget_link'),  # External Calget calendar link
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Insert event
            result = self.supabase.table('events').insert(event_record).execute()
            
            if result.data:
                logger.info(f"Created event: {event_data['title']}")
                # Clean the response before returning
                cleaned_event = self._clean_event_response(result.data[0])
                return {'success': True, 'data': cleaned_event}
            else:
                return {'success': False, 'error': 'Failed to create event'}
                
        except Exception as e:
            logger.error(f"Error creating event: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def update_event(
        self,
        event_id: str,
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an event (admin functionality)"""
        try:
            # Add updated timestamp
            update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Update the event
            result = self.supabase.table('events').update(update_data).eq('id', event_id).execute()
            
            if result.data:
                logger.info(f"Updated event {event_id} with: {list(update_data.keys())}")
                # Clean the response before returning
                cleaned_event = self._clean_event_response(result.data[0])
                return {'success': True, 'data': cleaned_event}
            else:
                return {'success': False, 'error': 'Failed to update event'}
                
        except Exception as e:
            logger.error(f"Error updating event {event_id}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # REMOVED: Registration now handled via Calget
    # The following methods have been removed as registration is now handled externally:
    # - register_for_event()
    # - cancel_registration() 
    # - get_user_events()
    # - generate_calendar_file()
    # - _process_waitlist()
    
    async def get_event_tags(self) -> Dict[str, Any]:
        """Get available event tags for filtering"""
        try:
            # For now, return predefined tags
            # In future, this could query from a tags table
            tags = [
                {'value': 'webinar', 'label': 'Webinar'},
                {'value': 'workshop', 'label': 'Workshop'},
                {'value': 'networking', 'label': 'Networking'},
                {'value': 'masterclass', 'label': 'Masterclass'},
                {'value': 'q-and-a', 'label': 'Q&A Session'},
                {'value': 'case-study', 'label': 'Case Study'},
            ]
            
            return {'success': True, 'data': tags}
            
        except Exception as e:
            logger.error(f"Error getting event tags: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def submit_event_feedback(
        self,
        event_id: str,
        user_id: str,
        feedback_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit feedback for an event"""
        try:
            # Check if user attended the event
            # With Calget integration, we'll skip this check
            
            # Create feedback record
            feedback_id = str(uuid.uuid4())
            feedback_record = {
                'id': feedback_id,
                'event_id': event_id,
                'user_id': user_id,
                'rating': feedback_data.get('rating'),
                'comments': feedback_data.get('comments'),
                'would_recommend': feedback_data.get('would_recommend', True),
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Store feedback (table would need to be created)
            # For now, just log it
            logger.info(f"Event feedback submitted: {feedback_record}")
            
            return {
                'success': True,
                'message': 'Feedback submitted successfully',
                'feedback_id': feedback_id
            }
            
        except Exception as e:
            logger.error(f"Error submitting feedback: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def _enrich_events_with_user_data(self, events: List[Dict], user_id: str) -> List[Dict]:
        """Add user-specific data to events (registration status, etc.)"""
        try:
            # With Calget integration, registration status is not tracked internally
            # Just return events as-is
            return events
            
        except Exception as e:
            logger.error(f"Error enriching events: {str(e)}")
            return events
    
    async def _schedule_event_reminders(self, event_id: str, user_id: str):
        """Schedule reminder emails for an event"""
        try:
            # With Calget integration, reminders are handled by Calget
            logger.info(f"Reminder scheduling now handled by Calget for event {event_id}")
            pass
                
        except Exception as e:
            logger.error(f"Error scheduling reminders: {str(e)}")
    
    def _clean_event_response(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Remove unwanted fields from a single event response"""
        if isinstance(event, dict):
            # Remove the specified fields
            event.pop('meeting_url', None)
            event.pop('replay_video_url', None)
            event.pop('tags', None)
        return event
    
    def _clean_event_responses(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove unwanted fields from multiple event responses"""
        return [self._clean_event_response(event) for event in events]

# Global instance
events_service = EventsService()