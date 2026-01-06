# PodGround Backend API

FastAPI backend for PodGround landing page with A/B testing and Customer.io waitlist integration.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy environment file and configure:
```bash
cp .env.example .env
```

3. Set your environment variables in `.env`:
- `ENVIRONMENT`: Environment (dev or prod)
- `CUSTOMERIO_API_KEY`: Your Customer.io Pipelines API key
- `CUSTOMERIO_DEV_SEGMENT_ID`: Your development segment ID
- `CUSTOMERIO_PROD_SEGMENT_ID`: Your production segment ID
- `CAPTCHA_SECRET_KEY`: Your Google reCAPTCHA secret key

## Running Locally

```bash
uvicorn main:app --reload
```

API will be available at `http://localhost:8000`

## API Endpoints

- `GET /api/v1/ab-variant` - Get A/B test variant (round-robin)
- `GET /api/v1/token` - Generate JWT token for waitlist submission
- `POST /api/v1/waitlist` - Submit email to waitlist (requires JWT token)
- `POST /api/v1/microgrant-waitlist` - Submit email to microgrant waitlist (requires JWT token)
- `GET /api/v1/resources/blogs` - Get all blog posts
- `GET /api/v1/resources/blogs/category/{category_id}` - Get blog posts by category
- `GET /api/v1/health` - Health check
- `GET /api/v1/customerio-info` - Customer.io integration status (debug)
- `GET /api/v1/debug/waitlist` - View recent waitlist entries (debug)
- `GET /api/v1/debug/microgrant-waitlist` - View recent microgrant waitlist entries (debug)

## Deployment

Deploy to Render using the included `render.yaml` configuration. Set environment variables in Render dashboard.