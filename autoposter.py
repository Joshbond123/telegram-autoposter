# autoposter.py
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
from config import API_ID, API_HASH, SESSION_FILE, GROUPS_FILE, MESSAGES_FILE, SCHEDULER_FILE, LOGS_FILE

scheduler = BackgroundScheduler()
job_id = 'autopost_job'

def get_client():
    return TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def post_message(group_id, message):
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

def load_json(file, default=None):
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default if default is not None else {}
    return default if default is not None else {}

def save_json(file, data):
    try:
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {file}: {e}")

def append_log(entry):
    logs = load_json(LOGS_FILE, [])
    logs.append(entry)
    save_json(LOGS_FILE, logs)

def autopost():
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
        append_log({'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resting', 'error': None})
        return

    messages = load_json(MESSAGES_FILE, [])
    groups = load_json(GROUPS_FILE, [])
    enabled_groups = [g for g in groups if g.get('enabled')]
    if not messages or not enabled_groups:
        append_log({'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Failed', 'error': 'No messages or enabled groups'})
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
        seconds = interval['value'] * (60 if interval['unit'] == 'minutes' else 3600)
        config['next_time'] = time.ctime(current_time + seconds)
    else:
        times = config.get('fixed_times', [])
        config['next_time'] = min(times, default='N/A')

    save_json(SCHEDULER_FILE, config)

    for group in enabled_groups:
        success, error = asyncio.run(post_message(group['id'], selected_message))
        preview = selected_message['text'][:50] + ('...' if len(selected_message['text']) > 50 else '') if selected_message['text'] else 'Media'
        if selected_message['media']:
            preview += f" [Media: {len(selected_message['media'])} file(s)]"
        append_log({'timestamp': time.ctime(), 'group': group['name'], 'message_preview': preview, 'status': 'Success' if success else 'Failed', 'error': error})
        if success:
            group['last_sent'] = time.ctime()

    save_json(GROUPS_FILE, groups)

def resume_after_rest():
    config = load_json(SCHEDULER_FILE, {})
    config['is_resting'] = False
    config['last_start'] = time.time()
    config['activity_duration'] = random.randint(30, 60) * 60
    config['rest_duration'] = random.randint(10, 15) * 60
    interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
    config['next_time'] = time.ctime(time.time() + interval['value'] * 60)
    save_json(SCHEDULER_FILE, config)
    scheduler.resume_job(job_id)
    append_log({'timestamp': time.ctime(), 'group': 'All', 'message_preview': 'N/A', 'status': 'Resumed', 'error': None})

def start_scheduler():
    config = load_json(SCHEDULER_FILE, {'mode': 'interval', 'interval': {'value': 15, 'unit': 'minutes'}, 'active': False})
    if not config.get('active'):
        return

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if config['mode'] == 'interval':
        interval = config.get('interval', {'value': 15, 'unit': 'minutes'})
        seconds = interval['value'] * (60 if interval['unit'] == 'minutes' else 3600)
        scheduler.add_job(autopost, IntervalTrigger(seconds=seconds), id=job_id)
    else:
        for t in config.get('fixed_times', []):
            try:
                hour, minute = map(int, t.split(':'))
                scheduler.add_job(autopost, CronTrigger(hour=hour, minute=minute), id=f"{job_id}_{t}")
            except ValueError:
                continue

    if not scheduler.running:
        scheduler.start()
