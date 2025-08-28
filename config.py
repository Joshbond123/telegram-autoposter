# config.py
import os

API_ID = 29390017
API_HASH = 'dec686aa277bc1445033485033486fe4f71035'

STORAGE_FOLDER = 'storage'
UPLOAD_FOLDER = 'static/uploads'

SESSION_FILE = os.path.join(STORAGE_FOLDER, 'session')
GROUPS_FILE = os.path.join(STORAGE_FOLDER, 'groups.json')
MESSAGES_FILE = os.path.join(STORAGE_FOLDER, 'messages.json')
SCHEDULER_FILE = os.path.join(STORAGE_FOLDER, 'scheduler.json')
LOGS_FILE = os.path.join(STORAGE_FOLDER, 'logs.json')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'doc', 'docx'}

# Ensure storage directories exist
os.makedirs(STORAGE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
