#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
OPERATOR_EMAIL = os.getenv('OPERATOR_EMAIL')


def _parse_body(event):
    if isinstance(event, dict):
        raw = event.get('body', '')
        if isinstance(raw, str):
            return json.loads(raw) if raw.strip() else {}
        return raw or {}
    if isinstance(event, str):
        return json.loads(event) if event.strip() else {}
    return {}


def _http(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handle(event, context):
    try:
        data = _parse_body(event)
        subject = data.get('subject', 'Дайджест просроченных заявок')
        text = data.get('body') or data.get('text')
        if text is None:
            text = json.dumps(data, ensure_ascii=False)

        msg = MIMEText(str(text), 'plain', 'utf-8')
        msg['From'] = SMTP_USER
        msg['To'] = OPERATOR_EMAIL
        msg['Subject'] = subject

        logging.info("Отправка письма оператору %s", OPERATOR_EMAIL)
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
        return _http(200, {"ok": True})
    except Exception as exc:
        logging.exception("Ошибка отправки письма")
        return _http(500, {"error": str(exc)})
