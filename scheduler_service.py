import os
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from contextlib import asynccontextmanager
import asyncio

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = None
        self.is_running = False
    
    async def start(self):
        """Start the scheduler"""
        if self.scheduler is not None:
            logger.warning("Scheduler is already running")
            return
        
        try:
            # Create scheduler with asyncio support
            self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
            
            # Add scheduled jobs
            await self._add_scheduled_jobs()
            
            # Start the scheduler
            self.scheduler.start()
            self.is_running = True
            
            logger.info("APScheduler started successfully with scheduled background tasks")
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {str(e)}")
            self.scheduler = None
    
    async def stop(self):
        """Stop the scheduler"""
        if self.scheduler is not None:
            self.scheduler.shutdown()
            self.scheduler = None
            self.is_running = False
            logger.info("APScheduler stopped")
    
    async def _add_scheduled_jobs(self):
        """Add all scheduled jobs to the scheduler"""
        
        # Import background task functions
        from background_tasks import send_signup_reminders, send_podcast_claim_reminders, sync_signup_confirmations, sync_failed_waitlist_entries, process_event_reminders, categorize_uncategorized_podcasts, import_claimed_podcasts, refresh_featured_podcast_episodes, refresh_stale_podcast_episodes
        
        # Job 1: Send signup reminders every hour for users who signed up 24+ hours ago
        self.scheduler.add_job(
            send_signup_reminders,
            trigger=CronTrigger(minute=0),  # Run every hour at minute 0
            id="signup_reminders",
            name="Send Signup Reminders",
            misfire_grace_time=300,  # 5 minutes grace time
            coalesce=True,  # Combine multiple missed executions into one
            max_instances=1  # Prevent overlapping executions
        )
        
        # Job 2: Send podcast claim reminders every hour for claims 24+ hours old
        self.scheduler.add_job(
            send_podcast_claim_reminders,
            trigger=CronTrigger(minute=15),  # Run every hour at minute 15
            id="podcast_claim_reminders",
            name="Send Podcast Claim Reminders",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1
        )
        
        # Job 3: Sync confirmed signups to Customer.io (configurable interval)
        sync_confirmations_hours = int(os.getenv('SYNC_CONFIRMATIONS_HOURS', '2'))
        self.scheduler.add_job(
            sync_signup_confirmations,
            trigger=CronTrigger(minute=30, hour=f"*/{sync_confirmations_hours}"),
            id="sync_confirmations",
            name="Sync Signup Confirmations",
            misfire_grace_time=600,  # 10 minutes grace time
            coalesce=True,
            max_instances=1
        )
        logger.info(f"Sync signup confirmations scheduled every {sync_confirmations_hours} hours")

        # Job 4: Sync failed waitlist entries to Customer.io (configurable interval)
        sync_waitlist_hours = int(os.getenv('SYNC_FAILED_WAITLIST_HOURS', '6'))
        self.scheduler.add_job(
            sync_failed_waitlist_entries,
            trigger=IntervalTrigger(hours=sync_waitlist_hours),
            id="sync_failed_waitlist",
            name="Sync Failed Waitlist Entries",
            misfire_grace_time=300,  # 5 minute grace time
            coalesce=True,
            max_instances=1  # Prevent overlapping executions
        )
        logger.info(f"Sync failed waitlist scheduled every {sync_waitlist_hours} hours")
        
        # Job 6: Process event reminders every 5 minutes
        # self.scheduler.add_job(
        #     process_event_reminders,
        #     trigger=IntervalTrigger(minutes=5),  # Check for event reminders every 5 minutes
        #     id="process_event_reminders",
        #     name="Process Event Reminders",
        #     misfire_grace_time=60,  # 1 minute grace time
        #     coalesce=True,
        #     max_instances=1
        # )
        
        # Job 7: Categorize uncategorized podcasts once daily using Gemini AI
        self.scheduler.add_job(
            categorize_uncategorized_podcasts,
            trigger=CronTrigger(hour=2, minute=0),  # Run daily at 2:00 AM UTC
            id="categorize_podcasts",
            name="Categorize Uncategorized Podcasts",
            misfire_grace_time=600,  # 10 minutes grace time for daily job
            coalesce=True,
            max_instances=1
        )
        
        # Job 8: Import claimed podcasts into main table (interval configurable via env var)
        import_interval_minutes = int(os.getenv('CLAIMED_PODCASTS_IMPORT_INTERVAL_MINUTES', '30'))
        self.scheduler.add_job(
            import_claimed_podcasts,
            trigger=IntervalTrigger(minutes=import_interval_minutes),
            id="import_claimed_podcasts",
            name="Import Claimed Podcasts",
            misfire_grace_time=60,  # 1 minute grace time
            coalesce=True,
            max_instances=1
        )
        logger.info(f"Claimed podcasts import job scheduled to run every {import_interval_minutes} minutes")
        
        # Job 9: Refresh featured podcast episodes with expired TTL cache (configurable interval)
        featured_refresh_hours = int(os.getenv('FEATURED_EPISODES_REFRESH_HOURS', '2'))
        self.scheduler.add_job(
            refresh_featured_podcast_episodes,
            trigger=CronTrigger(minute=10, hour=f"*/{featured_refresh_hours}"),
            id="refresh_featured_episodes",
            name="Refresh Featured Podcast Episodes",
            misfire_grace_time=600,  # 10 minutes grace time
            coalesce=True,
            max_instances=1
        )
        logger.info(f"Featured podcast episodes refresh scheduled every {featured_refresh_hours} hours")

        # Job 10: Refresh very stale podcast episodes (configurable interval)
        stale_refresh_hours = int(os.getenv('STALE_EPISODES_REFRESH_HOURS', '4'))
        self.scheduler.add_job(
            refresh_stale_podcast_episodes,
            trigger=CronTrigger(minute=20, hour=f"*/{stale_refresh_hours}"),
            id="refresh_stale_episodes",
            name="Refresh Stale Podcast Episodes",
            misfire_grace_time=600,  # 10 minutes grace time
            coalesce=True,
            max_instances=1
        )
        logger.info(f"Stale podcast episodes refresh scheduled every {stale_refresh_hours} hours")

        logger.info("Added 9 scheduled jobs: signup_reminders, podcast_claim_reminders, sync_confirmations, sync_failed_waitlist, process_event_reminders, categorize_podcasts, import_claimed_podcasts, refresh_featured_episodes, refresh_stale_episodes")
    
    def get_job_status(self) -> dict:
        """Get status of all scheduled jobs"""
        if not self.scheduler:
            return {"scheduler_running": False, "jobs": []}
        
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger)
            })
        
        return {
            "scheduler_running": self.is_running,
            "jobs": jobs
        }

# Global scheduler instance
scheduler_service = SchedulerService()