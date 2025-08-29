# config.py: Shared configuration for Telegram Auto-Poster
# Updated to use environment variables for API credentials
# Holds file paths to avoid circular imports; used by main.py and autoposter.py

import os

# Telegram API credentials (set as environment variables in Render for security)
API_ID = int(os.getenv('API_ID', '29390017'))  # Fallback to provided value
API_HASH = os.getenv('API_HASH', 'dec686aa277bc1445033486fe4f71035')  # Fallback to provided value

# Storage paths (persistent on Render with Persistent Disk)
STORAGE_FOLDER = 'storage'
UPLOAD_FOLDER = 'static/uploads'

# File paths
SESSION_FILE = os.path.join(STORAGE_FOLDER, 'session')
GROUPS_FILE = os.path.join(STORAGE_FOLDER, 'groups.json')
MESSAGES_FILE = os.path.join(STORAGE_FOLDER, 'messages.json')
SCHEDULER_FILE = os.path.join(STORAGE_FOLDER, 'scheduler.json')
LOGS_FILE = os.path.join(STORAGE_FOLDER, 'logs.json')

# Ensure directories exist
os.makedirs(STORAGE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
