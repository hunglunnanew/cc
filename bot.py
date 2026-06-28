import os
import asyncio
import json
import base64
import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime, timezone
from google.cloud.firestore_v1.base_query import FieldFilter

# Check if Firebase is already initialized
if not firebase_admin._apps:
    try:
        service_account_b64 = os.environ.get('FIREBASE_SERVICE_ACCOUNT_BASE64')
        if service_account_b64:
            service_account_info = json.loads(base64.b64decode(service_account_b64).decode('utf-8'))
            cred = credentials.Certificate(service_account_info)
            print("Loaded Firebase credentials from base64 env var.")
        else:
            cred = credentials.Certificate('serviceAccountKey.json')
            print("Loaded Firebase credentials from file.")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Error initializing Firebase: {e}")

db = firestore.client()

def send_fcm_notification(title, body, sender_id=None):
    try:
        users = db.collection('users').get()
        tokens = []
        for u in users:
            if u.id != sender_id: # Don't notify the sender
                token = u.to_dict().get('fcmToken')
                if token:
                    tokens.append(token)
        
        if not tokens:
            return
            
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            tokens=tokens,
        )
        response = messaging.send_multicast(message)
        print(f"FCM: Sent {response.success_count} messages, {response.failure_count} failed.")
    except Exception as e:
        print(f"FCM Error: {e}")

def on_message_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == 'ADDED':
            msg_data = change.document.to_dict()
            sender_id = msg_data.get('senderId')
            sender_name = msg_data.get('senderName', 'Ai đó')
            text = msg_data.get('text', '')
            
            if not text and 'mediaURLs' in msg_data:
                text = "Đã gửi tệp đính kèm"
            elif not text and msg_data.get('type') == 'audio':
                text = "Đã gửi tin nhắn thoại"

            print(f"New Message from {sender_name}: {text}")
            send_fcm_notification(
                title=f"{sender_name} (Nhóm Chat)",
                body=text,
                sender_id=sender_id
            )

def on_call_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == 'ADDED':
            call_data = change.document.to_dict()
            caller_id = call_data.get('callerId')
            caller_name = call_data.get('callerName', 'Ai đó')
            call_type = call_data.get('type', 'audio')
            
            title = f"Cuộc gọi {call_type} đến"
            body = f"{caller_name} đang gọi cho bạn..."
            print(f"New Call: {title} - {body}")
            send_fcm_notification(
                title=title,
                body=body,
                sender_id=caller_id
            )

async def dummy_web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="Backend Notifier is running!")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

async def main():
    await dummy_web_server()
    print("Backend Notifier started! Listening to Firebase...")
    
    now = datetime.now(timezone.utc)
    
    # Listen to messages
    msgs_query = db.collection('chatRooms').document('global').collection('messages').where(filter=FieldFilter('createdAt', '>=', now))
    msgs_query.on_snapshot(on_message_snapshot)
    
    # Listen to calls
    calls_query = db.collection('calls').where(filter=FieldFilter('createdAt', '>=', now))
    calls_query.on_snapshot(on_call_snapshot)
    
    # Keep alive
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
