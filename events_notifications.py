"""
Events Notification System - Email notifications for event registrations and reminders
Integrates with Customer.io for professional email delivery
"""

import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import logging

from customerio_client import CustomerIOClient
from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

class EventsNotificationService:
    """Service for managing event-related email notifications"""

    def __init__(self):
        self.customerio = CustomerIOClient()
        self.supabase_client = get_supabase_client()
        self.supabase = self.supabase_client.service_client
    
    async def send_registration_confirmation(self, user_id: str, event_id: str, attendee_id: str) -> Dict:
        """Send registration confirmation email"""
        try:
            # Get event and user details
            event = await self._get_event_details(event_id)
            if not event:
                return {'success': False, 'error': 'Event not found'}
            
            user_data = await self._get_user_details(user_id)
            if not user_data:
                return {'success': False, 'error': 'User not found'}
            
            # Generate calendar attachment
            from events_service import events_service
            calendar_result = await events_service.generate_calendar_file(event_id, user_id)
            
            # Prepare email data
            email_data = {
                'event_title': event['title'],
                'event_description': event['description'][:200] + '...' if len(event['description']) > 200 else event['description'],
                'event_date': self._format_event_date(event['event_date']),
                'event_location': event.get('location', 'Virtual'),
                'meeting_url': event.get('meeting_url', ''),
                'add_to_calendar_url': f"/api/v1/events/{event_id}/calendar",
                'event_details_url': f"/events/{event_id}",
                'attendee_id': attendee_id,
                'is_paid': event.get('is_paid', False),
                'price': event.get('price', 0),
                'timezone': event.get('timezone', 'UTC')
            }
            
            # Send via Customer.io
            result = self.customerio.send_transactional_email(
                to_email=user_data['email'],
                template_id='event_registration_confirmation',
                template_data=email_data,
                from_name='PodGround Events'
            )
            
            if result['success']:
                logger.info(f"Registration confirmation sent to user {user_id} for event {event_id}")
                return {'success': True, 'message': 'Confirmation email sent'}
            else:
                logger.error(f"Failed to send confirmation email: {result['error']}")
                return {'success': False, 'error': result['error']}
                
        except Exception as e:
            logger.error(f"Error sending registration confirmation: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def send_event_reminder(self, user_id: str, event_id: str, reminder_type: str = '24h') -> Dict:
        """Send event reminder email"""
        try:
            # Get event and user details
            event = await self._get_event_details(event_id)
            if not event:
                return {'success': False, 'error': 'Event not found'}
            
            user_data = await self._get_user_details(user_id)
            if not user_data:
                return {'success': False, 'error': 'User not found'}
            
            # Determine reminder template and timing
            template_mapping = {
                '24h': 'event_reminder_24h',
                '1h': 'event_reminder_1h',
                '15m': 'event_reminder_15m'
            }
            
            template_id = template_mapping.get(reminder_type, 'event_reminder_24h')
            
            # Calculate time until event
            event_datetime = datetime.fromisoformat(event['event_date'].replace('Z', '+00:00'))
            time_until = event_datetime - datetime.now(timezone.utc)
            
            # Prepare email data
            email_data = {
                'event_title': event['title'],
                'event_description': event['description'][:150] + '...' if len(event['description']) > 150 else event['description'],
                'event_date': self._format_event_date(event['event_date']),
                'event_location': event.get('location', 'Virtual'),
                'meeting_url': event.get('meeting_url', ''),
                'join_event_url': event.get('meeting_url', f"/events/{event_id}"),
                'event_details_url': f"/events/{event_id}",
                'hours_until': max(0, int(time_until.total_seconds() / 3600)),
                'minutes_until': max(0, int(time_until.total_seconds() / 60)),
                'reminder_type': reminder_type,
                'timezone': event.get('timezone', 'UTC')
            }
            
            # Send via Customer.io
            result = self.customerio.send_transactional_email(
                to_email=user_data['email'],
                template_id=template_id,
                template_data=email_data,
                from_name='PodGround Events'
            )
            
            if result['success']:
                # Mark reminder as sent
                await self._mark_reminder_sent(event_id, user_id, reminder_type)
                logger.info(f"{reminder_type} reminder sent to user {user_id} for event {event_id}")
                return {'success': True, 'message': f'{reminder_type} reminder sent'}
            else:
                logger.error(f"Failed to send {reminder_type} reminder: {result['error']}")
                return {'success': False, 'error': result['error']}
                
        except Exception as e:
            logger.error(f"Error sending event reminder: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def send_event_cancelled_notification(self, event_id: str, reason: str = '') -> Dict:
        """Send cancellation notification to all registered attendees"""
        try:
            event = await self._get_event_details(event_id)
            if not event:
                return {'success': False, 'error': 'Event not found'}
            
            # Get all registered attendees
            attendees = self.supabase.table('event_attendees').select(
                'user_id'
            ).eq('event_id', event_id).eq('status', 'registered').execute()
            
            if not attendees.data:
                return {'success': True, 'message': 'No attendees to notify'}
            
            notifications_sent = 0
            for attendee in attendees.data:
                user_data = await self._get_user_details(attendee['user_id'])
                if user_data:
                    email_data = {
                        'event_title': event['title'],
                        'event_date': self._format_event_date(event['event_date']),
                        'cancellation_reason': reason,
                        'refund_info': 'Refunds will be processed within 3-5 business days.' if event.get('is_paid') else '',
                        'is_paid': event.get('is_paid', False),
                        'support_email': 'support@podground.com'
                    }
                    
                    result = self.customerio.send_transactional_email(
                        to_email=user_data['email'],
                        template_id='event_cancelled',
                        template_data=email_data,
                        from_name='PodGround Events'
                    )
                    
                    if result['success']:
                        notifications_sent += 1
            
            return {
                'success': True,
                'message': f'Cancellation notifications sent to {notifications_sent} attendees'
            }
            
        except Exception as e:
            logger.error(f"Error sending cancellation notifications: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def process_pending_reminders(self) -> Dict:
        """Process all pending event reminders"""
        try:
            now = datetime.now(timezone.utc)
            
            # Get reminders that should be sent
            reminders = self.supabase.table('event_reminders').select('*').eq(
                'status', 'pending'
            ).lte('scheduled_for', now.isoformat()).execute()
            
            processed = 0
            failed = 0
            
            for reminder in reminders.data or []:
                try:
                    result = await self.send_event_reminder(
                        reminder['user_id'],
                        reminder['event_id'],
                        reminder['reminder_type']
                    )
                    
                    if result['success']:
                        processed += 1
                    else:
                        failed += 1
                        # Mark as failed
                        self.supabase.table('event_reminders').update({
                            'status': 'failed'
                        }).eq('id', reminder['id']).execute()
                        
                except Exception as e:
                    failed += 1
                    logger.error(f"Failed to process reminder {reminder['id']}: {str(e)}")
            
            return {
                'success': True,
                'processed': processed,
                'failed': failed,
                'message': f'Processed {processed} reminders, {failed} failed'
            }
            
        except Exception as e:
            logger.error(f"Error processing pending reminders: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # Private helper methods
    
    async def _get_event_details(self, event_id: str) -> Optional[Dict]:
        """Get event details from database"""
        try:
            result = self.supabase.table('events').select('*').eq('id', event_id).single().execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting event details: {str(e)}")
            return None
    
    async def _get_user_details(self, user_id: str) -> Optional[Dict]:
        """Get user details for email sending"""
        try:
            # Try to get user from Supabase auth
            user_result = self.supabase_client.service_client.auth.admin.get_user_by_id(user_id)
            if user_result and user_result.user:
                return {
                    'email': user_result.user.email,
                    'user_metadata': user_result.user.user_metadata or {}
                }
            return None
        except Exception as e:
            logger.error(f"Error getting user details: {str(e)}")
            return None
    
    def _format_event_date(self, event_date: str) -> str:
        """Format event date for email templates"""
        try:
            dt = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
            return dt.strftime('%A, %B %d, %Y at %I:%M %p %Z')
        except Exception:
            return event_date
    
    async def _mark_reminder_sent(self, event_id: str, user_id: str, reminder_type: str):
        """Mark reminder as sent in database"""
        try:
            self.supabase.table('event_reminders').update({
                'status': 'sent',
                'sent_at': datetime.now(timezone.utc).isoformat()
            }).eq('event_id', event_id).eq('user_id', user_id).eq(
                'reminder_type', reminder_type
            ).execute()
        except Exception as e:
            logger.error(f"Error marking reminder as sent: {str(e)}")

# Global instance
events_notification_service = EventsNotificationService()