# config.py: Shared configuration for Telegram Auto-Poster
# Updated with provided Telegram API credentials, formatted correctly
# Holds file paths to avoid circular imports; used by main.py and autoposter.py

import os

# Telegram API credentials (verified as provided)
API_ID = 29390017
API_HASH = 'dec686aa277bc1445033486fe4f71035'

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
