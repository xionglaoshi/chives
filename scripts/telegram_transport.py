"""Telegram Bot API transport for a configured private chat."""
from pathlib import Path
import re

import httpx

LIMIT = 20 * 1024 * 1024


class Telegram:
    def __init__(self, config):
        token = config['key']
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
            raise ValueError('invalid Telegram token')
        self.api = 'https://api.telegram.org/bot' + token
        self.files = 'https://api.telegram.org/file/bot' + token
        self.target = config['target']

    def call(self, method, data, files=None):
        with httpx.Client(timeout=30) as client:
            args = {'json': data} if files is None else {'data': data, 'files': files}
            result = client.post(self.api + '/' + method, **args).raise_for_status().json()
        if not result.get('ok'):
            raise ValueError('Telegram rejected request')
        return result['result']

    def poll(self, cursor):
        updates = self.call('getUpdates', {'offset': int(cursor or 0), 'timeout': 20,
                                           'allowed_updates': ['message']})
        messages = []
        for update in updates:
            msg = update.get('message') or {}
            chat = msg.get('chat') or {}
            sender = msg.get('from') or {}
            if chat.get('type') != 'private' or str(chat.get('id')) != self.target or sender.get('is_bot'):
                continue
            photos = msg.get('photo') or []
            attachments = [(msg.get('document'), 'attachment'), (msg.get('voice'), 'voice.ogg'),
                           (msg.get('audio'), 'audio.mp3'), (photos[-1] if photos else None, 'image.jpg')]
            media = [{'id': file['file_id'], 'name': file.get('file_name') or name}
                     for file, name in attachments if file and file.get('file_id')]
            text = msg.get('text') or msg.get('caption') or ''
            if text or media:
                messages.append(dict(id=str(update['update_id']), context='', text=text, media=media))
        return {'cursor': str(updates[-1]['update_id'] + 1) if updates else cursor, 'messages': messages}

    def download(self, item):
        import base64
        file = self.call('getFile', {'file_id': item['id']})
        path = file['file_path']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', path) or '..' in path.split('/'):
            raise ValueError('invalid file path')
        body = bytearray()
        with httpx.stream('GET', self.files + '/' + path, timeout=25) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > LIMIT:
                    raise ValueError('Telegram attachment too large')
        return {'name': item['name'], 'data': base64.b64encode(body).decode()}

    def reply(self, text):
        # Stay within Telegram's UTF-16 limit even for all-emoji text.
        for start in range(0, len(text), 1900):
            self.call('sendMessage', {'chat_id': self.target, 'text': text[start:start + 1900]})

    def media_reply(self, path):
        file = Path(path)
        if file.stat().st_size > LIMIT:
            raise ValueError('Telegram attachment too large')
        extension = file.suffix.lower()
        method, field = ('sendPhoto', 'photo') if extension in ('.jpg', '.jpeg', '.png') else (
            ('sendVoice', 'voice') if extension in ('.ogg', '.mp3', '.m4a') else ('sendDocument', 'document'))
        with file.open('rb') as stream:
            self.call(method, {'chat_id': self.target}, {field: (file.name, stream)})
