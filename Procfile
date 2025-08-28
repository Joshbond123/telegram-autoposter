# Procfile: Render deployment configuration for Telegram Auto-Poster
# Uses Gunicorn with sync worker to run Flask app, handling Telethon’s async operations
# Timeout set to 120 seconds to accommodate Telegram API delays (e.g., group fetching, flood waits)
web: gunicorn main:app --worker-class sync --timeout 120