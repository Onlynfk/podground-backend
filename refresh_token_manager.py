import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from sqlalchemy.orm import Session
from database import RefreshToken
import logging

logger = logging.getLogger(__name__)

class RefreshTokenManager:
    """Manages long-lived refresh tokens for 90-day login sessions"""

    @staticmethod
    def generate_refresh_token() -> str:
        """Generate a cryptographically secure refresh token"""
        return secrets.token_urlsafe(32)  # 256-bit token

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash the token for secure database storage"""
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def create_refresh_token(
        db: Session,
        user_id: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        days_valid: int = 90
    ) -> str:
        """Create a new refresh token for the user"""
        try:
            # Generate token
            token = RefreshTokenManager.generate_refresh_token()
            token_hash = RefreshTokenManager.hash_token(token)

            # Set expiration (90 days from now)
            expires_at = datetime.now(timezone.utc) + timedelta(days=days_valid)

            # Create database record
            refresh_token = RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                user_agent=user_agent,
                ip_address=ip_address
            )

            db.add(refresh_token)
            db.commit()

            logger.info(f"Created refresh token for user {user_id}, expires {expires_at}")
            return token

        except Exception as e:
            logger.error(f"Failed to create refresh token: {str(e)}")
            db.rollback()
            raise

    @staticmethod
    def validate_refresh_token(db: Session, token: str) -> Optional[Dict]:
        """Validate refresh token and return user info if valid"""
        try:
            token_hash = RefreshTokenManager.hash_token(token)

            # Find non-revoked, non-expired token
            refresh_token = db.query(RefreshToken).filter(
                RefreshToken.token_hash == token_hash,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > datetime.now(timezone.utc)
            ).first()

            if not refresh_token:
                return None

            # Update last used timestamp
            refresh_token.last_used_at = datetime.now(timezone.utc)
            db.commit()

            return {
                "user_id": refresh_token.user_id,
                "token_id": refresh_token.id,
                "expires_at": refresh_token.expires_at
            }

        except Exception as e:
            logger.error(f"Failed to validate refresh token: {str(e)}")
            return None

    @staticmethod
    def revoke_refresh_token(db: Session, token: str) -> bool:
        """Revoke a specific refresh token"""
        try:
            token_hash = RefreshTokenManager.hash_token(token)

            refresh_token = db.query(RefreshToken).filter(
                RefreshToken.token_hash == token_hash
            ).first()

            if refresh_token:
                refresh_token.is_revoked = True
                db.commit()
                logger.info(f"Revoked refresh token for user {refresh_token.user_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to revoke refresh token: {str(e)}")
            return False

    @staticmethod
    def revoke_all_user_tokens(db: Session, user_id: str) -> int:
        """Revoke all refresh tokens for a user (e.g., on password change)"""
        try:
            count = db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False
            ).update({"is_revoked": True})

            db.commit()
            logger.info(f"Revoked {count} refresh tokens for user {user_id}")
            return count

        except Exception as e:
            logger.error(f"Failed to revoke user tokens: {str(e)}")
            return 0

    @staticmethod
    def cleanup_expired_tokens(db: Session) -> int:
        """Remove expired tokens from database (run periodically)"""
        try:
            count = db.query(RefreshToken).filter(
                RefreshToken.expires_at < datetime.now(timezone.utc)
            ).delete()

            db.commit()
            logger.info(f"Cleaned up {count} expired refresh tokens")
            return count

        except Exception as e:
            logger.error(f"Failed to cleanup expired tokens: {str(e)}")
            return 0

    @staticmethod
    def get_user_active_tokens(db: Session, user_id: str) -> list:
        """Get all active tokens for a user (for security dashboard)"""
        try:
            tokens = db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > datetime.now(timezone.utc)
            ).order_by(RefreshToken.last_used_at.desc()).all()

            return [{
                "id": token.id,
                "created_at": token.created_at,
                "last_used_at": token.last_used_at,
                "expires_at": token.expires_at,
                "user_agent": token.user_agent,
                "ip_address": token.ip_address
            } for token in tokens]

        except Exception as e:
            logger.error(f"Failed to get user tokens: {str(e)}")
            return []
