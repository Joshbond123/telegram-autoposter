# main.py: Telegram Auto-Poster Web Dashboard (Render-ready)
# Full rewrite with safe scheduler, async Telethon calls, Flask routes, uploads, JSON storage
# Handles login, 2FA, groups, messages, scheduling, logs, and test sending

import os
import json
import asyncio
import threading
import time
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

# -------------------- Scheduler Setup --------------------
@app.before_first_request
def initialize_scheduler():
    """Start scheduler in a background daemon thread safely for Render/Gunicorn."""
    threading.Thread(target=start_scheduler, daemon=True).start()

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

@app.route('/groups', methods=['GET', 'POST'])
def groups():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    if request.method == 'POST':
        selected_ids = request.form.getlist('enabled_groups')
        groups = load_json(GROUPS_FILE, [])
        for group in groups:
            group['enabled'] = str(group['id']) in selected_ids
        save_json(GROUPS_FILE, groups)
        flash('Groups updated.', 'success')
    if not os.path.exists(GROUPS_FILE) or request.args.get('refresh'):
        groups = asyncio.run(fetch_groups())
        existing = load_json(GROUPS_FILE, [])
        existing_map = {g['id']: g for g in existing}
        for group in groups:
            if group['id'] in existing_map:
                group['enabled'] = existing_map[group['id']]['enabled']
                group['last_sent'] = existing_map[group['id']].get('last_sent')
        save_json(GROUPS_FILE, groups)
    else:
        groups = load_json(GROUPS_FILE, [])
    if not groups:
        flash('No groups found. Join some groups/channels.', 'info')
    return render_template('groups.html', groups=groups)

@app.route('/messages', methods=['GET', 'POST'])
def messages():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('text', '')
        rotation = request.form.get('rotation', 'sequential')
        media_paths = []
        if 'media' in request.files:
            files = request.files.getlist('media')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    media_paths.append(file_path)
                elif file.filename:
                    flash(f'Invalid file: {file.filename}.', 'error')
        if not text and not media_paths:
            flash('Text or media required.', 'error')
            return render_template('messages.html')
        messages = load_json(MESSAGES_FILE, [])
        new_message = {
            'text': text,
            'media': media_paths,
            'caption': text if media_paths else '',
            'type': 'multi' if len(media_paths) > 1 else 'single'
        }
        messages.append(new_message)
        save_json(MESSAGES_FILE, messages)
        scheduler = load_json(SCHEDULER_FILE, {'rotation': 'sequential'})
        scheduler['rotation'] = rotation
        save_json(SCHEDULER_FILE, scheduler)
        flash('Message added.', 'success')
    messages = load_json(MESSAGES_FILE, [])
    scheduler = load_json(SCHEDULER_FILE, {'rotation': 'sequential'})
    return render_template('messages.html', messages=messages, rotation=scheduler['rotation'])

@app.route('/delete_message/<int:index>')
def delete_message(index):
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    messages = load_json(MESSAGES_FILE, [])
    if 0 <= index < len(messages):
        for media in messages[index]['media']:
            try:
                os.remove(media)
            except OSError:
                pass
        messages.pop(index)
        save_json(MESSAGES_FILE, messages)
        flash('Message deleted.', 'success')
    else:
        flash('Invalid message index.', 'error')
    return redirect(url_for('messages'))

@app.route('/delete_group/<int:id>')
def delete_group(id):
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    groups = load_json(GROUPS_FILE, [])
    groups = [g for g in groups if g['id'] != id]
    save_json(GROUPS_FILE, groups)
    flash('Group removed.', 'success')
    return redirect(url_for('groups'))

@app.route('/scheduler', methods=['GET', 'POST'])
def scheduler():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    config = load_json(SCHEDULER_FILE, {
        'mode': 'interval',
        'interval': {'value': 15, 'unit': 'minutes'},
        'active': False,
        'rotation': 'sequential'
    })
    if request.method == 'POST':
        mode = request.form.get('mode')
        if mode == 'interval':
            try:
                value = int(request.form.get('interval_value', 15))
                unit = request.form.get('interval_unit', 'minutes')
                if value <= 0:
                    raise ValueError
                config = {'mode': mode, 'interval': {'value': value, 'unit': unit}}
            except ValueError:
                flash('Invalid interval value.', 'error')
                return render_template('scheduler.html', config=config)
        elif mode == 'fixed':
            times = request.form.get('fixed_times', '').split(',')
            valid_times = []
            for t in times:
                t = t.strip()
                if t and ':' in t:
                    try:
                        hour, minute = map(int, t.split(':'))
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            valid_times.append(t)
                    except ValueError:
                        continue
            if not valid_times:
                flash('No valid times provided.', 'error')
                return render_template('scheduler.html', config=config)
            config = {'mode': mode, 'fixed_times': valid_times}
        else:
            flash('Invalid scheduling mode.', 'error')
            return render_template('scheduler.html', config=config)
        config['active'] = 'active' in request.form
        save_json(SCHEDULER_FILE, config)
        flash('Scheduler updated.', 'success')
    return render_template('scheduler.html', config=config)

@app.route('/logs')
def logs():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    logs = load_json(LOGS_FILE, [])
    return render_template('logs.html', logs=logs)

@app.route('/send_test')
def send_test():
    if not asyncio.run(is_authorized()):
        return redirect(url_for('login'))
    messages_list = load_json(MESSAGES_FILE, [])
    if not messages_list:
        flash('No messages to send.', 'error')
        return redirect(url_for('home'))
    test_message = messages_list[0]
    groups_list = load_json(GROUPS_FILE, [])
    enabled_groups = [g for g in groups_list if g['enabled']]
    if not enabled_groups:
        flash('No enabled groups.', 'error')
        return redirect(url_for('home'))
    for group in enabled_groups:
        success, error = asyncio.run(post_message(group['id'], test_message))
        if success:
            flash(f'Test sent to {group["name"]}.', 'success')
        else:
            flash(f'Failed to send to {group["name"]}: {error}', 'error')
    return redirect(url_for('home'))

# -------------------- Run Locally --------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
