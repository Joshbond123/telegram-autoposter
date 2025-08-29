# main.py: Flask application for Telegram Auto-Poster Web Dashboard
# Updated for Telethon 1.36.0 to avoid bug in 1.40.0, with improved error handling
# Handles Telegram auth, dashboard routes, file uploads, scheduling, message/group deletion
# Edge cases: invalid inputs, Telegram errors (flood, permissions, invalid API), JSON corruption,
# invalid delete indices/IDs, session expiration, file deletion failures
# Uses Bootstrap templates with icons for beautiful, responsive UI

import os
import json
import asyncio
from flask import Flask, render_template, request, redirect, url_for, flash, session
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, FloodWaitError, ApiIdInvalidError
from telethon.tl.types import Channel
from werkzeug.utils import secure_filename
from autoposter import start_scheduler, post_message
from config import API_ID, API_HASH, SESSION_FILE, GROUPS_FILE, MESSAGES_FILE, SCHEDULER_FILE, LOGS_FILE, UPLOAD_FOLDER

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'super_secret_key'  # Change in production
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB upload limit

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'doc', 'docx'}

def async_wrapper(coro):
    """Run async coroutine in Flask's sync context using a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(coro)
        return result
    except Exception as e:
        print(f"Async error: {e}")
        raise
    finally:
        # Ensure all async tasks and generators are cleaned up
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

def allowed_file(filename):
    """Validate uploaded file extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_client():
    """Create and return a Telethon client instance."""
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def is_authorized():
    """Check if Telegram session is authorized."""
    client = get_client()
    try:
        await client.connect()
        authorized = await client.is_user_authorized()
        return authorized
    except Exception:
        return False
    finally:
        await client.disconnect()

async def fetch_username():
    """Fetch logged-in Telegram username."""
    client = get_client()
    async with client:
        me = await client.get_me()
        return me.username if me else None

async def fetch_groups():
    """Fetch all groups/channels user is in (excludes left groups)."""
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
    """Safely load JSON data."""
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            flash('Corrupted data file. Using defaults.', 'error')
            return default if default is not None else []
    return default if default is not None else []

def save_json(file, data):
    """Save data to JSON file."""
    try:
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving JSON {file}: {e}")

# Start background scheduler
start_scheduler()

@app.route('/')
def index():
    """Root route: Redirect to home if authorized, else login."""
    if async_wrapper(is_authorized()):
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page: Handles phone number input, sends Telegram code."""
    if request.method == 'POST':
        phone = request.form.get('phone')
        if not phone:
            flash('Phone number required.', 'error')
            return render_template('login.html')
        client = get_client()
        try:
            async def login_task():
                await client.connect()
                sent_code = await client.send_code_request(phone)
                return sent_code
            sent_code = async_wrapper(login_task())
            session['phone'] = phone
            session['phone_code_hash'] = sent_code.phone_code_hash
            flash('Code sent to Telegram.', 'success')
            return redirect(url_for('enter_code'))
        except ApiIdInvalidError:
            flash('Invalid API ID or API Hash. Please check credentials in settings.', 'error')
        except FloodWaitError as e:
            flash(f'Flood wait: {e.seconds} seconds. Please try again later.', 'error')
        except Exception as e:
            flash(f'Login error: {str(e)}', 'error')
        finally:
            async def disconnect_task():
                await client.disconnect()
            async_wrapper(disconnect_task())
    return render_template('login.html')

@app.route('/enter_code', methods=['GET', 'POST'])
def enter_code():
    """Code entry page: Verifies login code."""
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
            async def sign_in_task():
                await client.connect()
                await client.sign_in(session['phone'], code, phone_code_hash=session['phone_code_hash'])
            async_wrapper(sign_in_task())
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
            async def disconnect_task():
                await client.disconnect()
            async_wrapper(disconnect_task())
    return render_template('enter_code.html')

@app.route('/enter_password', methods=['GET', 'POST'])
def enter_password():
    """2FA password page: Verifies password."""
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
            async def sign_in_password_task():
                await client.connect()
                await client.sign_in(password=password)
            async_wrapper(sign_in_password_task())
            flash('2FA verified!', 'success')
            return redirect(url_for('home'))
        except PasswordHashInvalidError:
            flash('Invalid password.', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        finally:
            async def disconnect_task():
                await client.disconnect()
            async_wrapper(disconnect_task())
    return render_template('enter_password.html')

@app.route('/home')
def home():
    """Home page: Displays overview (username, last message, next schedule, enabled groups)."""
    if not async_wrapper(is_authorized()):
        return redirect(url_for('login'))
    username = async_wrapper(fetch_username()) or 'Unknown'
    messages = load_json(MESSAGES_FILE, [])
    last_message = messages[-1] if messages else {'text': 'None', 'media': [], 'caption': ''}
    scheduler = load_json(SCHEDULER_FILE, {'next_time': 'N/A'})
    groups = load_json(GROUPS_FILE, [])
    enabled_groups = len([g for g in groups if g['enabled']])
    return render_template('home.html', username=username, last_message=last_message, next_time=scheduler.get('next_time', 'N/A'), enabled_groups=enabled_groups)

@app.route('/groups', methods=['GET', 'POST'])
def groups():
    """Groups page: Lists groups with checkboxes, saves enabled status."""
    if not async_wrapper(is_authorized()):
        return redirect(url_for('login'))
    if request.method == 'POST':
        selected_ids = request.form.getlist('enabled_groups')
        groups = load_json(GROUPS_FILE, [])
        for group in groups:
            group['enabled'] = str(group['id']) in selected_ids
        save_json(GROUPS_FILE, groups)
        flash('Groups updated.', 'success')
    if not os.path.exists(GROUPS_FILE) or request.args.get('refresh'):
        groups = async_wrapper(fetch_groups())
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
    """Messages page: Composes messages with text/media, saves to JSON."""
    if not async_wrapper(is_authorized()):
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
                    flash(f'Invalid file: {file.filename}. Allowed: png, jpg, gif, mp4, pdf, doc, docx.', 'error')
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
    """Delete a message by index, including associated media files."""
    if not async_wrapper(is_authorized()):
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
    """Delete a group by ID from groups.json."""
    if not async_wrapper(is_authorized()):
        return redirect(url_for('login'))
    groups = load_json(GROUPS_FILE, [])
    groups = [g for g in groups if g['id'] != id]
    save_json(GROUPS_FILE, groups)
    flash('Group removed.', 'success')
    return redirect(url_for('groups'))

@app.route('/scheduler', methods=['GET', 'POST'])
def scheduler():
    """Scheduler page: Configures mode/interval/fixed times, active toggle."""
    if not async_wrapper(is_authorized()):
        return redirect(url_for('login'))
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
                flash('Invalid interval value (must be positive number).', 'error')
                return render_template('scheduler.html')
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
                flash('No valid times provided (use HH:MM, e
