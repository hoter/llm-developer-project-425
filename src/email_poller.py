#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from email.header import decode_header
import json
import logging
import os
import re
import urllib.request
from pathlib import Path

import openai

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
SMTP_PASSWORD = get_required_env('SMTP_PASSWORD')
IMAP_HOST = get_required_env('IMAP_HOST')
IMAP_USER = get_required_env('IMAP_USER')
IMAP_PASSWORD = get_required_env('IMAP_PASSWORD')
YC_FOLDER_ID = get_required_env('YC_FOLDER_ID')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
HELPDESK_MAILBOX = os.getenv('HELPDESK_MAILBOX', SMTP_USER)
MCP_SERVER_URL = os.getenv(
    'MCP_SERVER_URL',
    'https://db818p5vs9tr2fb1rdtj.5p9km096.mcpgw.serverless.yandexcloud.net/sse',
)
SEARCH_INDEX_ID = os.getenv('SEARCH_INDEX_ID', 'fvteblqas5msk531frfp')

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


def load_system_prompt():
    prompt_path = Path(__file__).with_name('agent_instructions.md')
    try:
        return prompt_path.read_text(encoding='utf-8').strip()
    except OSError:
        logging.warning("Не найден файл agent_instructions.md, системный промпт пуст.")
        return ""


def _get_iam_token():
    req = urllib.request.Request(
        "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data["access_token"]


def call_yandex_responses_api(text, sender_email):
    iam_token = _get_iam_token()
    client = openai.OpenAI(
        api_key=iam_token,
        project=YC_FOLDER_ID,
        base_url="https://ai.api.cloud.yandex.net/v1",
        timeout=60,
    )
    tools = [
        {
            "type": "file_search",
            "vector_store_ids": [SEARCH_INDEX_ID],
        },
        {
            "type": "mcp",
            "server_label": "ydb-tickets",
            "server_description": "Тикеты техподдержки: создать заявку, список заявок, добавить сообщение",
            "server_url": MCP_SERVER_URL,
            "require_approval": "never",
        },
    ]
    try:
        logging.warning("Responses API: model=%s tools=%d server_url=%s",
                        f"gpt://{YC_FOLDER_ID}/yandexgpt/latest", len(tools), MCP_SERVER_URL)
        prompt_text = f"Отправитель (email): {sender_email}\n\nОбращение:\n{text}"
        response = client.responses.create(
            model=f"gpt://{YC_FOLDER_ID}/yandexgpt/latest",
            instructions=load_system_prompt(),
            tools=tools,
            input=prompt_text,
        )
        summary = []
        for item in getattr(response, 'output', []):
            entry = {"type": getattr(item, "type", None)}
            name = getattr(item, "name", None)
            if name:
                entry["name"] = name
            if getattr(item, "type", None) == "message":
                entry["text"] = getattr(item, "output_text", None)
            summary.append(entry)
        logging.warning("Responses output: %s", summary)
        reply = response.output_text or ""
        for item in getattr(response, 'output', []):
            if getattr(item, 'type', None) != 'mcp_call' or getattr(item, 'name', None) != 'create-ticket':
                continue
            ticket_id = _ticket_id_from_mcp_output(getattr(item, 'output', None))
            if ticket_id and ticket_id not in reply:
                reply = reply.rstrip() + f"\n\nЗаявка № {ticket_id}"
        logging.warning("Responses final text: %s", reply[:500])
        return reply
    except Exception as e:
        logging.error(f"Ошибка вызова API: {e}")
        return "Извините, произошла ошибка при обращении к сервису."


def _ticket_id_from_mcp_output(raw):
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    body = payload.get('body') if isinstance(payload, dict) else None
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}
    if isinstance(body, dict):
        return body.get('ticket_id')
    return None


def main():
    try:
        logging.info("Подключение к IMAP...")
        imap = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        imap.login(IMAP_USER, IMAP_PASSWORD)
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
        api_response = call_yandex_responses_api(body, from_addr)

        reply_msg = MIMEMultipart()
        reply_msg['From'] = HELPDESK_MAILBOX
        reply_msg['To'] = from_addr
        reply_msg['Subject'] = reply_subject

        quoted = f"Вы писали:\n\n{body}\n\n" if body else ""
        reply_text = f"{quoted}{api_response}"

        reply_msg.attach(MIMEText(reply_text, 'plain', 'utf-8'))

        logging.info(f"Отправка ответа на {from_addr}")
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(reply_msg)

        imap.store(num, '+FLAGS', '\\Seen')
        logging.info(f"Письмо {num_str} помечено как прочитанное и обработано")

        imap.close()
        imap.logout()
        logging.info("Одно (самое новое) письмо успешно обработано.")

    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")


def handle(event, context):
    main()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True}),
    }


if __name__ == "__main__":
    main()