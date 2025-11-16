from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import os


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    Helps prevent XSS, clickjacking, and other security vulnerabilities.
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Get environment for conditional headers
        environment = os.getenv("ENVIRONMENT", "dev").lower()
        is_production = environment == "prod"
        
        # Security headers
        security_headers = {
            # Prevent clickjacking attacks
            "X-Frame-Options": "DENY",
            
            # Prevent MIME type sniffing
            "X-Content-Type-Options": "nosniff",
            
            # Enable XSS filtering in browsers
            "X-XSS-Protection": "1; mode=block",
            
            # Control referrer information
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Prevent Adobe Flash and PDF files from loading content
            "X-Permitted-Cross-Domain-Policies": "none",
            
            # Remove server information
            "Server": "PodGround-API",
        }
        
        # Add HSTS only in production with HTTPS
        if is_production:
            security_headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # Content Security Policy for API responses
        # Allow Swagger UI in development, restrictive in production
        if is_production:
            # Restrictive CSP for production API
            csp_directives = [
                "default-src 'none'",
                "frame-ancestors 'none'",
                "base-uri 'none'",
            ]
        else:
            # Allow Swagger UI resources in development
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
                "img-src 'self' data: https:",
                "font-src 'self' https://fonts.gstatic.com",
                "frame-ancestors 'none'",
                "base-uri 'self'",
            ]
        security_headers["Content-Security-Policy"] = "; ".join(csp_directives)
        
        # Permissions Policy (formerly Feature Policy)
        # Disable all potentially dangerous features for an API
        permissions_policy = [
            "accelerometer=()",
            "camera=()",
            "geolocation=()",
            "gyroscope=()",
            "magnetometer=()",
            "microphone=()",
            "payment=()",
            "usb=()",
        ]
        security_headers["Permissions-Policy"] = ", ".join(permissions_policy)
        
        # Add headers to response
        for header_name, header_value in security_headers.items():
            response.headers[header_name] = header_value
        
        return response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add rate limiting information to responses.
    Helps clients understand rate limiting status.
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add rate limiting headers if not already present
        if "X-RateLimit-Limit" not in response.headers:
            # Default rate limit info - actual limits are set per endpoint
            response.headers["X-RateLimit-Limit"] = "60"
            response.headers["X-RateLimit-Remaining"] = "59"
            response.headers["X-RateLimit-Reset"] = str(int(60))  # 60 seconds
        
        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for additional request validation and security checks.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Check for suspicious patterns in request
        if self._is_suspicious_request(request):
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request format"}
            )
        
        response = await call_next(request)
        return response
    
    def _is_suspicious_request(self, request: Request) -> bool:
        """Check for suspicious request patterns"""
        
        # Check for overly long URLs (potential buffer overflow)
        if len(str(request.url)) > 2048:
            return True
        
        # Check for suspicious user agents
        user_agent = request.headers.get("user-agent", "").lower()
        suspicious_patterns = [
            "sqlmap",
            "nikto",
            "nessus",
            "burp",
            "w3af",
            "havij",
            "masscan",
        ]
        
        for pattern in suspicious_patterns:
            if pattern in user_agent:
                return True
        
        # Check for suspicious headers
        dangerous_headers = [
            "x-forwarded-host",
            "x-original-url",
            "x-rewrite-url",
        ]
        
        for header in dangerous_headers:
            if header in request.headers:
                # Allow X-Forwarded-* headers from localhost (Next.js proxy)
                origin = request.headers.get("origin", "")
                if origin.startswith("http://localhost") or origin.startswith("https://localhost"):
                    continue  # Allow from localhost
                    
                # Allow X-Forwarded-Host only from trusted proxies in production
                if header == "x-forwarded-host":
                    environment = os.getenv("ENVIRONMENT", "dev")
                    if environment == "prod":
                        continue  # Allow in production
                else:
                    return True
        
        return False