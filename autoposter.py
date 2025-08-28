# autoposter.py: Background posting logic and scheduler for Telegram Auto-Poster
# Uses APScheduler to schedule posts (interval or fixed times), supports message rotation (sequential/random)
# Implements rest periods: pauses for 10-15 mins after 30-60 mins activity, resumes automatically
# Handles Telegram API via Telethon: sends text, media (images/videos/docs), supports captions, links, emojis
# Edge cases: no messages/groups (logs error), Telegram errors (flood, permissions), JSON corruption (falls back),
# network failures (retries via queue in main.py), invalid times in fixed mode (skips)
# Persists state in scheduler.json, logs in logs.json, updates groups.json with last_sent timestamps

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
from main import API_ID, API_HASH, SESSION_FILE, GROUPS_FILE, MESSAGES_FILE, SCHEDULER_FILE, LOGS_FILE  # Import configs

# Initialize APScheduler for background task scheduling
scheduler = BackgroundScheduler()
job_id = 'autopost_job'  # Unique ID for main posting job

def get_client():
    """Create and return a Telethon client instance using the session file."""
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def post_message(group_id, message):
    """Post a message to a group (text or media with caption). Returns (success, error)."""
    client = get_client()
    try:
        async with client:
            entity = await client.get_entity(group_id)
            if message['media']:
                # Send media (supports multiple files: images, videos, docs; handles captions, emojis, links)
                await client.send_file(entity, message['media'], caption=message['caption'], parse_mode='html')
            else:
                # Send text (supports markdown/HTML, emojis, links)
                await client.send_message(entity, message['text'], parse_mode='html')
        return True, None
    except FloodWaitError as e:
        return False, f'Flood wait: {e.seconds} seconds'
    except ChatWriteForbiddenError:
        return False, 'No permission to post in group'
    except Exception as e:
        return False, str(e)

def autopost():
    """Scheduled posting function: Selects message, posts to enabled groups, manages rest periods, logs results."""
    config = load_json(SCHEDULER_FILE, {'active': False, 'is_resting': False})
    if not config.get('active') or config.get('is_resting'):
        return  # Skip if scheduler inactive or in rest period
    
    # Check if activity period exceeded (30-60 mins)
    current_time = time.time()
    if current_time - config.get('last_start', 0) > config.get('activity_duration', 3600):
        # Start rest period (10-15 mins)
        config['is_resting'] = True
        config['rest_start'] = current_time
        config['next_time'] = time.ctime(current_time + config.get('rest_duration', 600))
        save_json(SCHEDULER_FILE, config)
        scheduler.pause_job(job_id)
        # Schedule resume after rest
        scheduler.add_job(resume_after_rest, 'date', run_date=current_time + config.get('rest_duration', 600))
        log_entry = {'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resting', 'error': None}
        append_log(log_entry)
        return
    
    # Load messages and groups
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
    
    # Select message based on rotation mode
    rotation = config.get('rotation', 'sequential')
    if rotation == 'sequential':
        current_index = config.get('current_message_index', 0)
        selected_message = messages[current_index]
        config['current_message_index'] = (current_index + 1) % len(messages)
    else:  # random
        selected_message = random.choice(messages)
    
    # Update next scheduled time
    if config.get('mode') == 'interval':
        interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
        seconds = interval['value']
        if interval['unit'] == 'minutes':
            seconds *= 60
        elif interval['unit'] == 'hours':
            seconds *= 3600
        config['next_time'] = time.ctime(current_time + seconds)
    else:  # fixed times
        times = config.get('fixed_times', [])
        if times:
            next_time = min(times, key=lambda t: int(t.replace(':', '')))
            config['next_time'] = next_time
        else:
            config['next_time'] = 'N/A'
    
    save_json(SCHEDULER_FILE, config)
    
    # Post to enabled groups and log results
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
    """Resume scheduler after rest period, reset activity duration."""
    config = load_json(SCHEDULER_FILE, {})
    config['is_resting'] = False
    config['last_start'] = time.time()
    config['activity_duration'] = random.randint(30, 60) * 60  # New random activity period (30-60 mins)
    config['rest_duration'] = random.randint(10, 15) * 60  # New random rest period (10-15 mins)
    config['next_time'] = time.ctime(time.time() + config.get('interval', {'value': 15, 'unit': 'minutes'})['value'] * 60)
    save_json(SCHEDULER_FILE, config)
    scheduler.resume_job(job_id)
    log_entry = {'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resumed', 'error': None}
    append_log(log_entry)

def load_json(file, default=None):
    """Load JSON file safely (edge case: file missing/corrupted → return default)."""
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default if default is not None else {}
    return default if default is not None else {}

def save_json(file, data):
    """Save data to JSON file (edge case: write failure → silent, but log in production)."""
    try:
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving JSON {file}: {e}")

def append_log(entry):
    """Append log entry to logs.json (edge case: file grows large → no truncation in this version)."""
    logs = load_json(LOGS_FILE, [])
    logs.append(entry)
    save_json(LOGS_FILE, logs)

def start_scheduler():
    """Start APScheduler with config from scheduler.json (interval or fixed times)."""
    config = load_json(SCHEDULER_FILE, {'mode': 'interval', 'interval': {'value': 15, 'unit': 'minutes'}, 'active': False})
    if not config.get('active'):
        return
    
    # Remove existing job if present
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Configure job based on mode
    if config['mode'] == 'interval':
        interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
        seconds = interval['value']
        if interval['unit'] == 'minutes':
            seconds *= 60
        elif interval['unit'] == 'hours':
            seconds *= 3600
        trigger = IntervalTrigger(seconds=seconds)
        scheduler.add_job(autopost, trigger, id=job_id)
    else:  # fixed times
        for t in config.get('fixed_times', []):
            try:
                hour, minute = map(int, t.split(':'))
                trigger = CronTrigger(hour=hour, minute=minute)
                scheduler.add_job(autopost, trigger, id=f"{job_id}_{t}")
            except ValueError:
                continue  # Skip invalid times
    
    if not scheduler.running:
        scheduler.start()