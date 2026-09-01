#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

import ydb


def read_statements(path):
    statements = []
    current = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('--'):
                continue
            current.append(line)
            if stripped.endswith(';'):
                statements.append(''.join(current))
                current = []
    if current:
        statements.append(''.join(current))
    return [s.strip() for s in statements if s.strip()]


def main():
    schema_path = sys.argv[1] if len(sys.argv) > 1 else 'src/ydb_tickets/schema.sql'
    endpoint = os.environ['YDB_ENDPOINT']
    database = os.environ['YDB_DATABASE']
    iam_token = os.environ['YC_IAM_TOKEN']

    driver = ydb.Driver(
        endpoint=endpoint,
        database=database,
        credentials=ydb.AccessTokenCredentials(iam_token),
    )
    driver.wait(timeout=10, fail_fast=True)

    for statement in read_statements(schema_path):
        print(f"-- executing: {statement[:90]}...")
        with driver.table_client.session() as session:
            session.execute_scheme(statement)


if __name__ == '__main__':
    main()
