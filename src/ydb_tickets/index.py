#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import datetime
import json
import logging
import os
import uuid

import ydb
import ydb.iam

ENDPOINT = os.getenv("YDB_ENDPOINT")
DATABASE = os.getenv("YDB_DATABASE")

VALID_CATEGORIES = {"bug", "docs", "feature", "access"}
VALID_ROLES = {"user", "agent"}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

_driver = None
_pool = None


def _get_pool():
    global _driver, _pool
    if _pool is None:
        _driver = ydb.Driver(
            endpoint=ENDPOINT,
            database=DATABASE,
            credentials=ydb.iam.MetadataUrlCredentials(),
        )
        _driver.wait(timeout=10, fail_fast=True)
        _pool = ydb.SessionPool(_driver)
    return _pool


def _exec(pool, yql, params):
    def run(session):
        prepared = session.prepare(yql)
        return session.transaction().execute(prepared, params, commit_tx=True)

    return pool.retry_operation_sync(run)


def _http(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def _require(data, name):
    value = data.get(name)
    if value is None or value == "":
        raise ValueError(f"Missing required field: {name}")
    return value


def _create_ticket(data):
    user_id = _require(data, "user_id")
    category = _require(data, "category")
    text = _require(data, "text")
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category: {category}")

    ticket_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    _exec(
        _get_pool(),
        """
        DECLARE $id AS Utf8;
        DECLARE $user_id AS Utf8;
        DECLARE $category AS Utf8;
        DECLARE $status AS Utf8;
        DECLARE $text AS Utf8;
        DECLARE $now AS Timestamp;
        UPSERT INTO tickets (id, user_id, category, status, text, created_at, updated_at)
        VALUES ($id, $user_id, $category, $status, $text, $now, $now);
        """,
        {
            "$id": ticket_id,
            "$user_id": user_id,
            "$category": category,
            "$status": "open",
            "$text": text,
            "$now": now,
        },
    )
    return {"ticket_id": ticket_id, "created_at": now.isoformat()}, 200


def _list_my_tickets(data):
    user_id = _require(data, "user_id")
    result_sets = _exec(
        _get_pool(),
        """
        DECLARE $user_id AS Utf8;
        SELECT id, status, category, text, created_at
        FROM tickets VIEW tickets_by_user
        WHERE user_id = $user_id
        ORDER BY created_at DESC;
        """,
        {"$user_id": user_id},
    )
    rows = result_sets[0].rows if result_sets else []
    tickets = [
        {
            "id": row.id,
            "status": row.status,
            "category": row.category,
            "text": row.text,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return tickets, 200


def _ticket_exists(pool, ticket_id):
    result_sets = _exec(
        pool,
        """
        DECLARE $ticket_id AS Utf8;
        SELECT id FROM tickets WHERE id = $ticket_id LIMIT 1;
        """,
        {"$ticket_id": ticket_id},
    )
    return bool(result_sets and result_sets[0].rows)


def _append_message(data):
    ticket_id = _require(data, "ticket_id")
    role = _require(data, "role")
    text = _require(data, "text")
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    pool = _get_pool()
    if not _ticket_exists(pool, ticket_id):
        return {"error": f"Ticket not found: {ticket_id}"}, 404

    message_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    model = data.get("model") if role == "agent" else None
    tokens_in = data.get("tokens_in") if role == "agent" else None
    tokens_out = data.get("tokens_out") if role == "agent" else None
    latency_ms = data.get("latency_ms") if role == "agent" else None

    yql_msg = """
        DECLARE $ticket_id AS Utf8;
        DECLARE $message_id AS Utf8;
        DECLARE $role AS Utf8;
        DECLARE $text AS Utf8;
        DECLARE $model AS Utf8?;
        DECLARE $tokens_in AS Uint64?;
        DECLARE $tokens_out AS Uint64?;
        DECLARE $latency_ms AS Uint32?;
        DECLARE $now AS Timestamp;
        UPSERT INTO messages (id, ticket_id, role, text, model, tokens_in, tokens_out, latency_ms, created_at)
        VALUES ($message_id, $ticket_id, $role, $text, $model, $tokens_in, $tokens_out, $latency_ms, $now);
    """
    yql_upd = """
        DECLARE $ticket_id AS Utf8;
        DECLARE $now AS Timestamp;
        UPDATE tickets SET updated_at = $now WHERE id = $ticket_id;
    """

    def run(session):
        prepared_msg = session.prepare(yql_msg)
        prepared_upd = session.prepare(yql_upd)
        tx = session.transaction()
        tx.execute(prepared_msg, {
            "$ticket_id": ticket_id,
            "$message_id": message_id,
            "$role": role,
            "$text": text,
            "$model": model,
            "$tokens_in": tokens_in,
            "$tokens_out": tokens_out,
            "$latency_ms": latency_ms,
            "$now": now,
        })
        tx.execute(prepared_upd, {
            "$ticket_id": ticket_id,
            "$now": now,
        }, commit_tx=True)

    pool.retry_operation_sync(run)
    return {"message_id": message_id, "ok": True}, 200


def _parse_event(event):
    if isinstance(event, str):
        event = json.loads(event) if event.strip() else {}
    if not isinstance(event, dict):
        event = dict(event or {})
    if "httpMethod" in event:
        body = event.get("body")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        if isinstance(body, str) and body.strip():
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                event = parsed
    return event


def _detect_action(data):
    action = data.get("action")
    if action:
        return action
    if "ticket_id" in data:
        return "append-message"
    if "category" in data:
        return "create-ticket"
    if "user_id" in data:
        return "list-my-tickets"
    return None


def handle(event, context):
    try:
        data = _parse_event(event)
        action = _detect_action(data)

        if action == "create-ticket":
            body, code = _create_ticket(data)
        elif action == "list-my-tickets":
            body, code = _list_my_tickets(data)
        elif action == "append-message":
            body, code = _append_message(data)
        else:
            return _http(400, {"error": f"Unknown action: {action!r}"})

        return _http(code, body)
    except ValueError as exc:
        logging.warning("Invalid request: %s", exc)
        return _http(400, {"error": str(exc)})
    except Exception as exc:
        logging.exception("Handler error")
        return _http(500, {"error": str(exc)})


handler = handle
