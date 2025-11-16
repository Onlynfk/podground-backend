"""
Featured Content Service
Handles curation and management of featured podcasts and networks
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class FeaturedContentService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    # FEATURED PODCASTS MANAGEMENT
    async def set_podcast_featured(
        self,
        podcast_id: str,
        is_featured: bool,
        priority: int = 0,
        featured_until: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Set podcast as featured with optional expiry"""
        try:
            update_data = {
                'is_featured': is_featured,
                'featured_priority': priority if is_featured else 0
            }
            
            if is_featured and featured_until:
                update_data['featured_until'] = featured_until.isoformat()
            elif not is_featured:
                update_data['featured_until'] = None
            
            result = self.supabase.table('podcasts') \
                .update(update_data) \
                .eq('id', podcast_id) \
                .execute()
            
            if result.data:
                action = "featured" if is_featured else "unfeatured"
                logger.info(f"Podcast {podcast_id} {action} with priority {priority}")
                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "message": "Failed to update featured status"}
            
        except Exception as e:
            logger.error(f"Error setting podcast featured status: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def set_podcast_network(
        self,
        podcast_id: str,
        is_network: bool,
        network_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set podcast as network or assign to network"""
        try:
            update_data = {'is_network': is_network}
            
            if not is_network and network_id:
                # Assigning podcast to a network
                update_data['network_id'] = network_id
            elif is_network:
                # Making podcast a network (clear network_id)
                update_data['network_id'] = None
            
            result = self.supabase.table('podcasts') \
                .update(update_data) \
                .eq('id', podcast_id) \
                .execute()
            
            if result.data:
                logger.info(f"Podcast {podcast_id} network status updated")
                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "message": "Failed to update network status"}
            
        except Exception as e:
            logger.error(f"Error setting podcast network status: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def get_featured_dashboard(self) -> Dict[str, Any]:
        """Get dashboard view of featured content for admin"""
        try:
            # Get featured podcasts
            featured_podcasts = self.supabase.table('podcasts') \
                .select('id, title, publisher, image_url, is_featured, featured_priority, featured_until, follower_count, listen_score') \
                .eq('is_featured', True) \
                .order('featured_priority', desc=True) \
                .execute()
            
            # Get featured networks
            featured_networks = self.supabase.table('podcasts') \
                .select('id, title, publisher, image_url, is_featured, featured_priority, featured_until, follower_count') \
                .eq('is_network', True) \
                .eq('is_featured', True) \
                .order('featured_priority', desc=True) \
                .execute()
            
            # Get expiring featured content (next 7 days)
            expiring_date = datetime.now(timezone.utc) + timedelta(days=7)
            expiring_featured = self.supabase.table('podcasts') \
                .select('id, title, featured_until') \
                .eq('is_featured', True) \
                .not_.is_('featured_until', 'null') \
                .lte('featured_until', expiring_date.isoformat()) \
                .execute()
            
            return {
                'featured_podcasts': featured_podcasts.data,
                'featured_networks': featured_networks.data,
                'expiring_featured': expiring_featured.data,
                'stats': {
                    'total_featured_podcasts': len(featured_podcasts.data),
                    'total_featured_networks': len(featured_networks.data),
                    'expiring_soon': len(expiring_featured.data)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting featured dashboard: {e}")
            return {}
    
    async def cleanup_expired_featured(self) -> Dict[str, Any]:
        """Remove featured status from expired podcasts"""
        try:
            current_time = datetime.now(timezone.utc)
            
            result = self.supabase.table('podcasts') \
                .update({
                    'is_featured': False,
                    'featured_priority': 0,
                    'featured_until': None
                }) \
                .eq('is_featured', True) \
                .not_.is_('featured_until', 'null') \
                .lte('featured_until', current_time.isoformat()) \
                .execute()
            
            expired_count = len(result.data) if result.data else 0
            
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired featured podcasts")
            
            return {
                "success": True,
                "expired_count": expired_count,
                "cleaned_up": result.data
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up expired featured content: {e}")
            return {"success": False, "message": "Internal error"}
    
    # CONTENT CURATION
    async def suggest_featured_candidates(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Suggest podcasts that could be featured based on metrics"""
        try:
            # Find high-performing podcasts not currently featured
            result = self.supabase.table('podcasts') \
                .select('id, title, publisher, image_url, follower_count, listen_score, total_episodes, last_episode_date') \
                .eq('is_featured', False) \
                .gte('follower_count', 100)  \
                .gte('listen_score', 3.5) \
                .gte('total_episodes', 10) \
                .order('listen_score', desc=True) \
                .order('follower_count', desc=True) \
                .limit(limit) \
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.error(f"Error getting featured candidates: {e}")
            return []
    
    async def get_category_featured_status(self) -> Dict[str, Any]:
        """Get featured content distribution by category"""
        try:
            result = self.supabase.table('podcasts') \
                .select('''
                    category_id,
                    category:podcast_categories(name, display_name),
                    is_featured
                ''') \
                .execute()
            
            # Process data to show category distribution
            category_stats = {}
            for podcast in result.data:
                if podcast.get('category'):
                    cat_name = podcast['category']['display_name']
                    if cat_name not in category_stats:
                        category_stats[cat_name] = {'total': 0, 'featured': 0}
                    
                    category_stats[cat_name]['total'] += 1
                    if podcast['is_featured']:
                        category_stats[cat_name]['featured'] += 1
            
            # Calculate percentages and identify underrepresented categories
            for cat_name in category_stats:
                stats = category_stats[cat_name]
                stats['featured_percentage'] = (stats['featured'] / stats['total']) * 100 if stats['total'] > 0 else 0
                stats['needs_attention'] = stats['featured'] == 0 and stats['total'] >= 5
            
            return category_stats
            
        except Exception as e:
            logger.error(f"Error getting category featured status: {e}")
            return {}
    
    async def bulk_update_featured_priorities(self, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk update featured priorities for multiple podcasts"""
        try:
            successful_updates = []
            failed_updates = []
            
            for update in updates:
                try:
                    podcast_id = update.get('podcast_id')
                    priority = update.get('priority', 0)
                    
                    if not podcast_id:
                        failed_updates.append({'update': update, 'error': 'Missing podcast_id'})
                        continue
                    
                    result = self.supabase.table('podcasts') \
                        .update({'featured_priority': priority}) \
                        .eq('id', podcast_id) \
                        .eq('is_featured', True) \
                        .execute()
                    
                    if result.data:
                        successful_updates.append(result.data[0])
                    else:
                        failed_updates.append({'update': update, 'error': 'Update failed or podcast not featured'})
                        
                except Exception as e:
                    failed_updates.append({'update': update, 'error': str(e)})
            
            return {
                'success': True,
                'successful_updates': len(successful_updates),
                'failed_updates': len(failed_updates),
                'details': {
                    'successful': successful_updates,
                    'failed': failed_updates
                }
            }
            
        except Exception as e:
            logger.error(f"Error bulk updating featured priorities: {e}")
            return {"success": False, "message": "Internal error"}
    
    # ANALYTICS
    async def get_featured_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for featured content"""
        try:
            # Calculate date range
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)
            
            # Get featured podcasts
            featured_podcasts = self.supabase.table('podcasts') \
                .select('id, title, follower_count, listen_score, is_featured') \
                .eq('is_featured', True) \
                .execute()
            
            if not featured_podcasts.data:
                return {'message': 'No featured podcasts found'}
            
            podcast_ids = [p['id'] for p in featured_podcasts.data]
            
            # Get follow activity for featured podcasts in date range
            follow_activity = self.supabase.table('user_podcast_follows') \
                .select('podcast_id, followed_at') \
                .in_('podcast_id', podcast_ids) \
                .gte('followed_at', start_date.isoformat()) \
                .execute()
            
            # Get listening activity for featured podcasts' episodes
            episodes_result = self.supabase.table('episodes') \
                .select('id, podcast_id') \
                .in_('podcast_id', podcast_ids) \
                .execute()
            
            episode_ids = [e['id'] for e in episodes_result.data]
            
            if episode_ids:
                listening_activity = self.supabase.table('user_listening_progress') \
                    .select('episode_id, started_at, is_completed') \
                    .in_('episode_id', episode_ids) \
                    .gte('started_at', start_date.isoformat()) \
                    .execute()
            else:
                listening_activity = {'data': []}
            
            # Process metrics
            total_new_follows = len(follow_activity.data)
            total_listening_sessions = len(listening_activity.data)
            completed_sessions = len([l for l in listening_activity.data if l['is_completed']])
            
            # Calculate per-podcast metrics
            podcast_metrics = []
            for podcast in featured_podcasts.data:
                podcast_id = podcast['id']
                podcast_follows = len([f for f in follow_activity.data if f['podcast_id'] == podcast_id])
                
                # Get episodes for this podcast
                podcast_episodes = [e['id'] for e in episodes_result.data if e['podcast_id'] == podcast_id]
                podcast_listening = [l for l in listening_activity.data if l['episode_id'] in podcast_episodes]
                
                podcast_metrics.append({
                    'podcast_id': podcast_id,
                    'title': podcast['title'],
                    'current_followers': podcast['follower_count'],
                    'current_rating': podcast['listen_score'],
                    'new_follows_period': podcast_follows,
                    'listening_sessions_period': len(podcast_listening),
                    'completion_rate': len([l for l in podcast_listening if l['is_completed']]) / len(podcast_listening) * 100 if podcast_listening else 0
                })
            
            return {
                'period_days': days,
                'summary': {
                    'total_featured_podcasts': len(featured_podcasts.data),
                    'total_new_follows': total_new_follows,
                    'total_listening_sessions': total_listening_sessions,
                    'completion_rate': (completed_sessions / total_listening_sessions * 100) if total_listening_sessions > 0 else 0
                },
                'podcast_metrics': podcast_metrics
            }
            
        except Exception as e:
            logger.error(f"Error getting featured performance metrics: {e}")
            return {"error": "Failed to get metrics"}
    
    async def get_trending_content_for_featuring(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get trending content that could be considered for featuring"""
        try:
            # Base query for non-featured podcasts with good metrics
            query = self.supabase.table('podcasts') \
                .select('*')
            
            if category_id:
                query = query.eq('category_id', category_id)
            
            # Look for recent activity and good scores
            recent_date = datetime.now(timezone.utc) - timedelta(days=30)
            result = query \
                .eq('is_featured', False) \
                .gte('last_episode_date', recent_date.isoformat()) \
                .gte('follower_count', 50) \
                .gte('listen_score', 3.0) \
                .order('listen_score', desc=True) \
                .order('follower_count', desc=True) \
                .order('last_episode_date', desc=True) \
                .limit(15) \
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.error(f"Error getting trending content for featuring: {e}")
            return []