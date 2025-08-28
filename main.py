# main.py: Telegram Auto-Poster Web Dashboard (Render-ready)
# Handles Telegram login, groups, messages, scheduling, uploads
# Uses Flask, Telethon, APScheduler, and asyncio safely with Gunicorn

import os
import json
import asyncio
import threading
import time
import random
from flask import Flask, render_template, request, redirect, url_for, flash, session
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, FloodWaitError
from telethon.tl.types import Channel
from werkzeug.utils import secure_filename
from autoposter import start_scheduler, post_message  # Your scheduler functions

# -------------------- Flask App Setup --------------------
app = Flask(__name__)
app.secret_key = 'super_secret_key'  # Change in production
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# -------------------- Telegram API Credentials --------------------
API_ID = 29390017
API_HASH = 'dec686aa277bc1445033485033486fe4f71035'

# -------------------- Storage Setup --------------------
STORAGE_FOLDER = 'storage'
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
os.makedirs(STORAGE_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SESSION_FILE = os.path.join(STORAGE_FOLDER, 'session')
GROUPS_FILE = os.path.join(STORAGE_FOLDER, 'groups.json')
MESSAGES_FILE = os.path.join(STORAGE_FOLDER, 'messages.json')
SCHEDULER_FILE = os.path.join(STORAGE_FOLDER, 'scheduler.json')
LOGS_FILE = os.path.join(STORAGE_FOLDER, 'logs.json')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------- Telethon Client Helpers --------------------
def get_client():
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def is_authorized():
    client = get_client()
    try:
        await client.connect()
        return await client.is_user_authorized()
    except Exception:
        return False
    finally:
        await client.disconnect()

async def fetch_username():
    client = get_client()
    async with client:
        me = await client.get_me()
        return me.username if me else None

async def fetch_groups():
    client = get_client()
    groups = []
    async with client:
        dialogs = await client.get_dialogs()
        for dialog in dialogs:
            entity = dialog.entity
            if isinstance(entity, Channel) and (entity.megagroup or entity.broadcast) and not entity.left:
                groups.append({'id': entity.id, 'name': entity.title, 'enabled': False, 'last_sent': None})
    return groups

# -------------------- JSON Storage Helpers --------------------
def load_json(file, default=None):
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            flash('Corrupted data file. Using defaults.', 'error')
            return default if default is not None else []
    return default if default is not None else []

def save_json(file, data):
    try:
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving JSON {file}: {e}")

# -------------------- Scheduler Startup --------------------
def start_scheduler_thread():
    """Start APScheduler in a background thread."""
    threading.Thread(target=start_scheduler, daemon=True).start()

@app.before_first_request
def initialize():
    start_scheduler_thread()

# -------------------- Flask Routes --------------------
@app.route('/')
def index():
    if asyncio.run(is_authorized()):
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone')
        if not phone:
            flash('Phone number required.', 'error')
            return render_template('login.html')
        client = get_client()
        try:
            asyncio.run(client.connect())
            sent_code = asyncio.run(client.send_code_request(phone))
            session['phone'] = phone
            session['phone_code_hash'] = sent_code.phone_code_hash
            flash('Code sent to Telegram.', 'success')
            return redirect(url_for('enter_code'))
        except FloodWaitError as e:
            flash(f'Flood wait: {e.seconds} seconds.', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        finally:
            asyncio.run(client.disconnect())
    return render_template('login.html')

@app.route('/enter_code', methods=['GET', 'POST'])
def enter_code():
    if 'phone' not in session or 'phone_code_hash' not in session:
        flash('Enter phone number first.', 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        code = request.form.get('code')
        if not code:
            flash('Code required.', 'error')
            return render_template('enter_code.html')
        client = get_client()
        try:
            asyncio.run(client.connect())
            asyncio.run(client.sign_in(session['phone'], code, phone_code_hash=session['phone_code_hash']))
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        except SessionPasswordNeededError:
            flash('Enter 2FA password.', 'info')
            return redirect(url_for('enter_password'))
        except PhoneCodeInvalidError:
            flash('Invalid code.', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        finally:
            asyncio.run(client.disconnect())
    return render_template('enter_code.html')

@app.route('/enter_password', methods=['GET', 'POST'])
def enter_password():
    if 'phone' not in session:
        flash('Session expired. Restart login.', 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        password = request.form.get('password')
        if not password:
            flash('Password required.', 'error')
            return render_template('enter_password.html')
        client = get_client()
        try:
            asyncio.run(client.connect())
            asyncio.run(client.sign_in(password=password))
            flash('2FA verified!', 'success')
            return redirect(url_for('home'))
        except PasswordHashInvalidError:
            flash('Invalid password.', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        finally:
            asyncio.run(client.disconnect())
    return render_template('enter_password.html')

@app.route('/home')
def home():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    username = asyncio.run(fetch_username()) or 'Unknown'
    messages = load_json(MESSAGES_FILE, [])
    last_message = messages[-1] if messages else {'text': 'None', 'media': [], 'caption': ''}
    scheduler = load_json(SCHEDULER_FILE, {'next_time': 'N/A'})
    groups = load_json(GROUPS_FILE, [])
    enabled_groups = len([g for g in groups if g['enabled']])
    return render_template('home.html', username=username, last_message=last_message,
                           next_time=scheduler.get('next_time', 'N/A'), enabled_groups=enabled_groups)

# -------------------- Add your remaining routes here --------------------
# groups, messages, delete_message, delete_group, scheduler, logs, send_test
# (Keep them as in your original code, they will work unchanged)

# -------------------- Local Testing --------------------
if __name__ == '__main__':
    start_scheduler()  # Only for local test
    app.run(debug=False, host='0.0.0.0', port=5000)
