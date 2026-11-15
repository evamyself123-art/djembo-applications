import os
import json
import uuid
import re
import requests
import redis
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 45 * 1024 * 1024
CORS(app, resources={r'/submit': {'origins': [
    'https://join-djembo.com', 'https://www.join-djembo.com',
    'https://evamyself123-art.github.io'
]}})
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')  # Use private group chat ID for manager access
REDIS_URL = os.environ.get('REDIS_URL')
store = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}

@app.get('/')
def home():
    return jsonify(status='DJEMBO server running')

@app.post('/submit')
def submit():
    if not BOT_TOKEN or not CHAT_ID or store is None:
        return jsonify(error='Server not configured: token, chat ID or Redis missing'), 503
    submission_id = request.form.get('submission_id', '')
    try:
        uuid.UUID(submission_id)
    except (ValueError, TypeError):
        return jsonify(error='Invalid submission ID'), 400
    key = 'djembo:submission:' + submission_id
    try:
        # SET NX is atomic across workers. Keep completed and uncertain submissions
        # from being sent twice. Never auto-retry partially sent Telegram batches.
        acquired = store.set(key, 'processing', nx=True, ex=60*60*24*30)
        if not acquired:
            state = store.get(key)
            if state == 'completed':
                return jsonify(success=True, duplicate=True)
            return jsonify(error='Заявка уже обрабатывается или требует проверки. Не отправляй повторно.'), 409
    except redis.RedisError:
        app.logger.exception('Redis unavailable')
        return jsonify(error='Temporary storage error'), 503
    sent_any = False
    try:
        answers = json.loads(request.form.get('answers', '{}'))
        if not isinstance(answers, dict):
            raise ValueError('Invalid answers')
        photos = request.files.getlist('photos')
        if not 5 <= len(photos) <= 10:
            raise ValueError('Нужно прикрепить от 5 до 10 фотографий')
        for photo in photos:
            if photo.mimetype not in ALLOWED_TYPES:
                raise ValueError('Допустимы только JPEG, PNG и WebP')
            if len(photo.read(10*1024*1024+1)) > 10*1024*1024:
                raise ValueError('Файл больше 10 МБ')
            photo.seek(0)
        if not answers.get('Твой Telegram для связи (@username)', '').strip().startswith('@'):
            raise ValueError('Укажи Telegram @username')
        message = '\n'.join(['Новая анкета DJEMBO', 'ID: '+submission_id, ''] +
            [f'{k}\n{", ".join(map(str,v)) if isinstance(v,list) else v}\n' for k,v in answers.items()])
        url = f'https://api.telegram.org/bot{BOT_TOKEN}'
        for start in range(0, len(message), 3500):
            resp = requests.post(url+'/sendMessage', data={'chat_id':CHAT_ID, 'text':message[start:start+3500]}, timeout=30)
            resp.raise_for_status()
            if not resp.json().get('ok'): raise RuntimeError('Telegram rejected message')
            sent_any = True
        for photo in photos:
            resp = requests.post(url+'/sendDocument', data={'chat_id':CHAT_ID, 'caption':'Заявка '+submission_id},
                files={'document':(secure_filename(photo.filename) or 'photo.jpg',photo.stream,photo.mimetype)}, timeout=60)
            resp.raise_for_status()
            if not resp.json().get('ok'): raise RuntimeError('Telegram rejected file')
            sent_any = True
        store.set(key, 'completed', ex=60*60*24*30)
        return jsonify(success=True)
    except (ValueError, json.JSONDecodeError) as exc:
        # Invalid input has not been sent; allow corrected retry with same ID.
        store.delete(key)
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception('Submission failed; ID %s; partial=%s', submission_id, sent_any)
        # Keep the lock even if the failure occurred before a response: a timeout
        # may mean Telegram accepted the data. Manual reconciliation is safer.
        store.set(key, 'needs_review', ex=60*60*24*30)
        return jsonify(error='Не удалось подтвердить отправку. Свяжись с @djemboreq, указав ID: '+submission_id), 502

@app.errorhandler(413)
def too_large(error):
    return jsonify(error='Общий размер файлов превышает 45 МБ'), 413

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
