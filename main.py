# main.py
import os
import json
import asyncio
import threading
from flask import Flask, render_template, request, redirect, url_for, flash, session
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, FloodWaitError
from telethon.tl.types import Channel
from werkzeug.utils import secure_filename
from autoposter import start_scheduler, post_message
from config import API_ID, API_HASH, STORAGE_FOLDER, UPLOAD_FOLDER, SESSION_FILE, GROUPS_FILE, MESSAGES_FILE, SCHEDULER_FILE, LOGS_FILE, ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# -------------------- Helpers --------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

# -------------------- Scheduler --------------------
@app.before_first_request
def initialize_scheduler():
    threading.Thread(target=start_scheduler, daemon=True).start()

# -------------------- Routes --------------------
@app.route('/')
def index():
    return redirect(url_for('home') if asyncio.run(is_authorized()) else url_for('login'))

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
            flash(f'Error: {e}', 'error')
        finally:
            asyncio.run(client.disconnect())
    return render_template('login.html')

# ... Continue all other routes exactly like your previous main.py code ...

# -------------------- Run --------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
