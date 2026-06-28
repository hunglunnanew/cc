import os
import sys
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore, storage
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- CONFIGURATION ---
API_ID = os.environ.get('API_ID', 26739747)
API_HASH = os.environ.get('API_HASH', "020a33a1f2ee15d4c8714c8324f2bd34")
SESSION_NAME = "my_userbot"
FIREBASE_KEY_PATH = "chat-realtime-33099-firebase-adminsdk-fbsvc-8f26895968.json"
STORAGE_BUCKET = os.environ.get('STORAGE_BUCKET', "chat-realtime-33099.appspot.com")

# Bot usernames on Telegram to forward links to
TIKTOK_BOT = "@ttsavebot"
IG_BOT = "@SaveAsbot"

# --- INIT FIREBASE ---
import json
if os.environ.get('FIREBASE_SERVICE_ACCOUNT_BASE64'):
    import base64
    cred_json = base64.b64decode(os.environ.get('FIREBASE_SERVICE_ACCOUNT_BASE64')).decode('utf-8')
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
elif os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    cred_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)

firebase_admin.initialize_app(cred, {
    'storageBucket': STORAGE_BUCKET
})
db = firestore.client()
bucket = storage.bucket()

# --- INIT TELETHON ---
session_string = os.environ.get('TELEGRAM_SESSION_STRING', '')
if session_string:
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
else:
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def upload_to_firebase(local_path, destination_blob_name):
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(local_path)
    blob.make_public()
    return blob.public_url

async def process_media_command(msg_data, msg_id, url, bot_username):
    try:
        # Update original message to show loading
        db.collection('messages').document(msg_id).update({
            'text': f"⏳ Đang xử lý link: {url}..."
        })

        # Send link to the telegram bot
        print(f"Sending {url} to {bot_username}...")
        await client.send_message(bot_username, url)

        # Wait for the bot to reply with a video
        video_path = None
        
        # Simple wait loop (in production, use event listener with Future)
        # Here we just wait for the next message from the bot
        async with client.conversation(bot_username, timeout=30) as conv:
            response = await conv.get_response()
            if response.media:
                print("Received media, downloading...")
                video_path = await response.download_media()
            else:
                # Sometimes bots send a text first, then media
                response2 = await conv.get_response()
                if response2.media:
                    print("Received media, downloading...")
                    video_path = await response2.download_media()
        
        if video_path:
            print(f"Downloaded to {video_path}, uploading to Firebase...")
            file_name = f"bot_media/{os.path.basename(video_path)}"
            public_url = await upload_to_firebase(video_path, file_name)
            
            # Update the message in Firebase
            db.collection('messages').document(msg_id).update({
                'text': '',
                'mediaURL': public_url,
                'mediaType': 'video'
            })
            
            # Clean up local file
            os.remove(video_path)
            print("Done!")
        else:
            db.collection('messages').document(msg_id).update({
                'text': f"❌ Không thể tải video từ {url}. (Bot không phản hồi media)"
            })
            
    except Exception as e:
        print("Error processing media:", e)
        db.collection('messages').document(msg_id).update({
            'text': f"❌ Lỗi xử lý: {str(e)}"
        })

import requests

async def process_soundcloud_command(msg_data, msg_id, url):
    try:
        db.collection('messages').document(msg_id).update({
            'text': f"⏳ Đang tải audio: {url}..."
        })
        
        # Call the API
        api_url = f"https://p.savenow.to/api/ajaxSearch?q={url}&vt=home"
        response = requests.post(api_url)
        data = response.json()
        
        if data.get('status') == 'ok' and 'links' in data:
            # Assuming links contain MP3 download URLs
            download_url = data['links'].get('mp3', {}).get('url') or data.get('url')
            
            if download_url:
                db.collection('messages').document(msg_id).update({
                    'text': '',
                    'mediaURL': download_url,
                    'mediaType': 'audio'
                })
            else:
                db.collection('messages').document(msg_id).update({
                    'text': f"❌ Không tìm thấy link tải từ SoundCloud."
                })
        else:
            db.collection('messages').document(msg_id).update({
                'text': f"❌ Lỗi khi lấy thông tin từ SoundCloud."
            })
            
    except Exception as e:
        print("Error processing SoundCloud:", e)
        db.collection('messages').document(msg_id).update({
            'text': f"❌ Lỗi xử lý: {str(e)}"
        })

def on_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == 'ADDED':
            msg_data = change.document.to_dict()
            msg_id = change.document.id
            text = msg_data.get('text', '')
            
            if text.startswith('/tik '):
                url = text.split('/tik ')[1].strip()
                asyncio.run_coroutine_threadsafe(
                    process_media_command(msg_data, msg_id, url, TIKTOK_BOT), 
                    client.loop
                )
            elif text.startswith('/ig '):
                url = text.split('/ig ')[1].strip()
                asyncio.run_coroutine_threadsafe(
                    process_media_command(msg_data, msg_id, url, IG_BOT), 
                    client.loop
                )
            elif text.startswith('/sc '):
                url = text.split('/sc ')[1].strip()
                asyncio.run_coroutine_threadsafe(
                    process_soundcloud_command(msg_data, msg_id, url), 
                    client.loop
                )

async def dummy_web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="Bot is running!")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Dummy web server started on port {port}")

async def main():
    # Start Dummy Web Server FIRST so Render health checks pass immediately
    await dummy_web_server()

    if not os.environ.get('TELEGRAM_SESSION_STRING'):
        print("ERROR: TELEGRAM_SESSION_STRING is missing! Please add it in Render Environment Variables.")
        # We don't exit so the web server stays alive to serve 502/200, but bot won't work
        # To avoid blocking, we just return or wait
        while True:
            await asyncio.sleep(3600)

    try:
        await client.start()
        print("Userbot started! Listening to Firebase...")
        
        from datetime import datetime, timezone
        from google.cloud.firestore_v1.base_query import FieldFilter
        now = datetime.now(timezone.utc)
        # Listen to Firebase messages created after this exact moment
        col_query = db.collection('messages').where(filter=FieldFilter('createdAt', '>=', now))
        col_query.on_snapshot(on_snapshot)
        
        # Keep running
        await client.run_until_disconnected()
    except Exception as e:
        print(f"Error starting Telegram Client: {e}")
        while True:
            await asyncio.sleep(3600)

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
