#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from email.header import decode_header
import urllib.request
import urllib.error
import json
import logging
import os
import re
from pathlib import Path

# ---------- ЗАГРУЗКА ПЕРЕМЕННЫХ ИЗ .env ----------
def load_env(env_path='.env'):
    env_vars = {}
    if not Path(env_path).exists():
        logging.warning(f"Файл {env_path} не найден, используются системные переменные окружения.")
        return env_vars
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars

env = load_env()
for k, v in env.items():
    if k not in os.environ:
        os.environ[k] = v

# ---------- КОНФИГУРАЦИЯ ----------
def get_required_env(name):
    value = os.getenv(name)
    if value is None:
        raise EnvironmentError(f"Не задана обязательная переменная окружения: {name}")
    return value

SMTP_HOST = get_required_env('SMTP_HOST')
SMTP_USER = get_required_env('SMTP_USER')
SMTP_PASS = get_required_env('SMTP_PASS')
IMAP_HOST = get_required_env('IMAP_HOST')
IMAP_USER = get_required_env('IMAP_USER')
IMAP_PASS = get_required_env('IMAP_PASS')
API_KEY   = get_required_env('YANDEX_API_KEY')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def decode_subject(subject):
    if subject is None:
        return ''
    parts = []
    for chunk, encoding in decode_header(subject):
        if isinstance(chunk, bytes):
            try:
                decoded = chunk.decode(encoding if encoding else 'utf-8',
                                       errors='replace')
            except (LookupError, UnicodeDecodeError):
                decoded = chunk.decode('utf-8', errors='replace')
            parts.append(decoded)
        else:
            parts.append(chunk)
    return ''.join(parts)


def get_plain_text_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get('Content-Disposition', ''))
            if content_type == 'text/plain' and 'attachment' not in disposition:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                try:
                    return payload.decode(charset, errors='replace')
                except LookupError:
                    return payload.decode('utf-8', errors='replace')
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get('Content-Disposition', ''))
            if content_type == 'text/html' and 'attachment' not in disposition:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                try:
                    html = payload.decode(charset, errors='replace')
                except LookupError:
                    html = payload.decode('utf-8', errors='replace')
                plain = re.sub(r'<[^>]+>', ' ', html)
                plain = re.sub(r'\s+', ' ', plain).strip()
                return plain
    else:
        if msg.get_content_type() == 'text/plain':
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            try:
                return payload.decode(charset, errors='replace')
            except LookupError:
                return payload.decode('utf-8', errors='replace')
    return None


def call_yandex_responses_api(text, api_key):
    url = 'https://rest-assistant.api.cloud.yandex.net/v1/responses'
    headers = {
        'Authorization': f'Api-Key {api_key}',
        'Content-Type': 'application/json'
    }
    payload = json.dumps({'text': text}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode('utf-8'))
            if 'response' in resp_data:
                return resp_data['response']
            elif 'result' in resp_data:
                return resp_data['result']
            else:
                return json.dumps(resp_data, ensure_ascii=False)
    except urllib.error.URLError as e:
        logging.error(f"Ошибка вызова API: {e}")
        return "Извините, произошла ошибка при обращении к сервису."


def main():
    try:
        logging.info("Подключение к IMAP...")
        imap = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select('INBOX')

        status, data = imap.search(None, 'UNSEEN')
        if status != 'OK':
            logging.error("Ошибка поиска писем")
            return

        mail_ids = data[0].split()
        if not mail_ids:
            logging.info("Нет непрочитанных писем.")
            imap.close()
            imap.logout()
            return

        # ---------- БЕРЁМ САМОЕ НОВОЕ ПИСЬМО (последнее в списке) ----------
        num = mail_ids[-1]
        num_str = num.decode() if isinstance(num, bytes) else str(num)
        logging.info(f"Обработка самого нового непрочитанного письма {num_str} (всего непрочитанных: {len(mail_ids)})")

        status, msg_data = imap.fetch(num, '(RFC822)')
        if status != 'OK':
            logging.error(f"Не удалось получить письмо {num_str}")
            imap.close()
            imap.logout()
            return

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        from_header = msg.get('From')
        from_name, from_addr = parseaddr(from_header)
        if not from_addr:
            logging.warning(f"Нет отправителя для письма {num_str}, пропускаем и помечаем прочитанным.")
            imap.store(num, '+FLAGS', '\\Seen')
            imap.close()
            imap.logout()
            return

        subject = decode_subject(msg.get('Subject', ''))
        reply_subject = f"Re: {subject}" if subject else "Re: Ваше письмо"

        body = get_plain_text_body(msg)
        if body is None:
            logging.warning(f"Не удалось извлечь текст письма {num_str}, используем пустую строку.")
            body = ""

        logging.info(f"Вызов Yandex API для письма от {from_addr}")
        api_response = call_yandex_responses_api(body, API_KEY)

        reply_msg = MIMEMultipart()
        reply_msg['From'] = SMTP_USER
        reply_msg['To'] = from_addr
        reply_msg['Subject'] = reply_subject

        quoted = f"Вы писали:\n\n{body}\n\n" if body else ""
        reply_text = f"{quoted}{api_response}"

        reply_msg.attach(MIMEText(reply_text, 'plain', 'utf-8'))

        logging.info(f"Отправка ответа на {from_addr}")
        with smtplib.SMTP_SSL(SMTP_HOST, 465) as smtp:
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(reply_msg)

        imap.store(num, '+FLAGS', '\\Seen')
        logging.info(f"Письмо {num_str} помечено как прочитанное и обработано")

        imap.close()
        imap.logout()
        logging.info("Одно (самое новое) письмо успешно обработано.")

    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")


if __name__ == "__main__":
    main()