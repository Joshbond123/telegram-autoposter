# autoposter.py: Background posting logic and scheduler for Telegram Auto-Poster
# Updated to use config.py for constants, removing circular import with main.py
# Uses APScheduler for scheduling posts (interval or fixed times), supports message rotation
# Implements rest periods: pauses for 10-15 mins after 30-60 mins activity
# Handles Telegram API via Telethon: sends text, media, supports captions, links, emojis
# Edge cases: no messages/groups, Telegram errors (flood, permissions), JSON corruption,
# network failures (retries via queue in main.py), invalid times in fixed mode

import os
import json
import time
import random
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatWriteForbiddenError
from config import API_ID, API_HASH, SESSION_FILE, GROUPS_FILE, MESSAGES_FILE, SCHEDULER_FILE, LOGS_FILE  # Import configs

# Initialize APScheduler
scheduler = BackgroundScheduler()
job_id = 'autopost_job'

def get_client():
    """Create and return a Telethon client instance."""
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def post_message(group_id, message):
    """Post a message to a group (text or media with caption). Returns (success, error)."""
    client = get_client()
    try:
        async with client:
            entity = await client.get_entity(group_id)
            if message['media']:
                await client.send_file(entity, message['media'], caption=message['caption'], parse_mode='html')
            else:
                await client.send_message(entity, message['text'], parse_mode='html')
        return True, None
    except FloodWaitError as e:
        return False, f'Flood wait: {e.seconds} seconds'
    except ChatWriteForbiddenError:
        return False, 'No permission to post in group'
    except Exception as e:
        return False, str(e)

def autopost():
    """Scheduled posting: Selects message, posts to enabled groups, manages rest periods."""
    config = load_json(SCHEDULER_FILE, {'active': False, 'is_resting': False})
    if not config.get('active') or config.get('is_resting'):
        return
    
    current_time = time.time()
    if current_time - config.get('last_start', 0) > config.get('activity_duration', 3600):
        config['is_resting'] = True
        config['rest_start'] = current_time
        config['next_time'] = time.ctime(current_time + config.get('rest_duration', 600))
        save_json(SCHEDULER_FILE, config)
        scheduler.pause_job(job_id)
        scheduler.add_job(resume_after_rest, 'date', run_date=current_time + config.get('rest_duration', 600))
        log_entry = {'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resting', 'error': None}
        append_log(log_entry)
        return
    
    messages = load_json(MESSAGES_FILE, [])
    groups = load_json(GROUPS_FILE, [])
    enabled_groups = [g for g in groups if g.get('enabled')]
    if not messages or not enabled_groups:
        log_entry = {
            'timestamp': time.ctime(),
            'group': 'All',
            'message_preview': 'N/A',
            'status': 'Failed',
            'error': 'No messages or enabled groups'
        }
        append_log(log_entry)
        return
    
    rotation = config.get('rotation', 'sequential')
    if rotation == 'sequential':
        current_index = config.get('current_message_index', 0)
        selected_message = messages[current_index]
        config['current_message_index'] = (current_index + 1) % len(messages)
    else:
        selected_message = random.choice(messages)
    
    if config.get('mode') == 'interval':
        interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
        seconds = interval['value']
        if interval['unit'] == 'minutes':
            seconds *= 60
        elif interval['unit'] == 'hours':
            seconds *= 3600
        config['next_time'] = time.ctime(current_time + seconds)
    else:
        times = config.get('fixed_times', [])
        if times:
            next_time = min(times, key=lambda t: int(t.replace(':', '')))
            config['next_time'] = next_time
        else:
            config['next_time'] = 'N/A'
    
    save_json(SCHEDULER_FILE, config)
    
    for group in enabled_groups:
        success, error = asyncio.run(post_message(group['id'], selected_message))
        preview = selected_message['text'][:50] + ('...' if len(selected_message['text']) > 50 else '') if selected_message['text'] else 'Media'
        if selected_message['media']:
            preview += f" [Media: {len(selected_message['media'])} file(s)]"
        log_entry = {
            'timestamp': time.ctime(),
            'group': group['name'],
            'message_preview': preview,
            'status': 'Success' if success else 'Failed',
            'error': error
        }
        append_log(log_entry)
        if success:
            group['last_sent'] = time.ctime()
    
    save_json(GROUPS_FILE, groups)

def resume_after_rest():
    """Resume scheduler after rest period."""
    config = load_json(SCHEDULER_FILE, {})
    config['is_resting'] = False
    config['last_start'] = time.time()
    config['activity_duration'] = random.randint(30, 60) * 60
    config['rest_duration'] = random.randint(10, 15) * 60
    config['next_time'] = time.ctime(time.time() + config.get('interval', {'value': 15, 'unit': 'minutes'})['value'] * 60)
    save_json(SCHEDULER_FILE, config)
    scheduler.resume_job(job_id)
    log_entry = {'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resumed', 'error': None}
    append_log(log_entry)

def load_json(file, default=None):
    """Load JSON file safely."""
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default if default is not None else {}
    return default if default is not None else {}

def save_json(file, data):
    """Save data to JSON file."""
    try:
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving JSON {file}: {e}")

def append_log(entry):
    """Append log entry to logs.json."""
    logs = load_json(LOGS_FILE, [])
    logs.append(entry)
    save_json(LOGS_FILE, logs)

def start_scheduler():
    """Start APScheduler with config from scheduler.json."""
    config = load_json(SCHEDULER_FILE, {'mode': 'interval', 'interval': {'value': 15, 'unit': 'minutes'}, 'active': False})
    if not config.get('active'):
        return
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    if config['mode'] == 'interval':
        interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
        seconds = interval['value']
        if interval['unit'] == 'minutes':
            seconds *= 60
        elif interval['unit'] == 'hours':
            seconds *= 3600
        trigger = IntervalTrigger(seconds=seconds)
        scheduler.add_job(autopost, trigger, id=job_id)
    else:
        for t in config.get('fixed_times', []):
            try:
                hour, minute = map(int, t.split(':'))
                trigger = CronTrigger(hour=hour, minute=minute)
                scheduler.add_job(autopost, trigger, id=f"{job_id}_{t}")
            except ValueError:
                continue
    
    if not scheduler.running:
        scheduler.start()
