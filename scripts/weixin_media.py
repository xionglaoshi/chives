"""Bounded Tencent iLink CDN media transport."""
import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

LIMIT = 20 * 1024 * 1024
CDN = 'https://novac2c.cdn.weixin.qq.com/c2c'


def cdn_url(url):
    u = urlsplit(url)
    if (u.scheme != 'https' or not (u.hostname or '').endswith('.cdn.weixin.qq.com')
            or u.username or u.password or u.port not in (443, None)):
        raise ValueError('invalid iLink CDN URL')
    return url


def decode_key(value):
    raw = base64.b64decode(value, validate=True)
    return bytes.fromhex(raw.decode('ascii')) if len(raw) == 32 else raw


def download(item):
    kind, key_name, fallback = {
        2: ('image', 'image_item', 'image.jpg'),
        3: ('voice', 'voice_item', 'voice.silk'),
        4: ('file', 'file_item', 'file'),
    }[item['type']]
    entry = item[key_name]
    media = entry['media']
    key = bytes.fromhex(entry['aeskey']) if entry.get('aeskey') else (
        decode_key(media['aes_key']) if media.get('aes_key') else None)
    if key is None and kind != 'image':
        raise ValueError('missing CDN key')
    url = cdn_url(media['full_url']) if media.get('full_url') else CDN + '/download'
    params = None if media.get('full_url') else {'encrypted_query_param': media['encrypt_query_param']}
    body = bytearray()
    with httpx.stream('GET', url, params=params, timeout=25) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > LIMIT + 16:
                raise ValueError('attachment exceeds limit')
    data = bytes(body)
    if key is not None:
        if len(key) != 16:
            raise ValueError('invalid CDN key')
        cipher = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        unpad = padding.PKCS7(128).unpadder()
        data = unpad.update(cipher.update(data) + cipher.finalize()) + unpad.finalize()
    if not data or len(data) > LIMIT:
        raise ValueError('invalid attachment size')
    if kind == 'image':
        fallback = ('image.png' if data.startswith(b'\x89PNG') else
                    'image.gif' if data.startswith(b'GIF8') else
                    'image.webp' if data[8:12] == b'WEBP' else 'image.jpg')
    return {'name': entry.get('file_name') or fallback, 'data': base64.b64encode(data).decode()}


def upload(path, client, api, headers, recipient):
    file = Path(path)
    with file.open('rb') as handle:
        data = handle.read(LIMIT + 1)
    if not data or len(data) > LIMIT:
        raise ValueError('invalid attachment size')
    image = file.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    key, filekey = os.urandom(16), uuid4().hex
    pad = padding.PKCS7(128).padder()
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    encrypted = cipher.update(pad.update(data) + pad.finalize()) + cipher.finalize()
    body = {'filekey': filekey, 'media_type': 1 if image else 3, 'to_user_id': recipient,
            'rawsize': len(data), 'rawfilemd5': hashlib.md5(data).hexdigest(),
            'filesize': len(encrypted), 'aeskey': key.hex(), 'no_need_thumb': True,
            'base_info': {'channel_version': '2.2.0'}}
    route = client.post(api + '/ilink/bot/getuploadurl', headers=headers, json=body).raise_for_status().json()
    url = cdn_url(route['upload_full_url']) if route.get('upload_full_url') else CDN + '/upload'
    params = None if route.get('upload_full_url') else {
        'encrypted_query_param': route['upload_param'], 'filekey': filekey}
    response = client.post(url, params=params, content=encrypted,
                           headers={'Content-Type': 'application/octet-stream'}).raise_for_status()
    media = {'encrypt_query_param': response.headers['x-encrypted-param'],
             'aes_key': base64.b64encode(key.hex().encode()).decode(), 'encrypt_type': 1}
    if image:
        return {'type': 2, 'image_item': {'media': media, 'mid_size': len(encrypted)}}
    return {'type': 4, 'file_item': {'media': media, 'file_name': file.name, 'len': str(len(data))}}
