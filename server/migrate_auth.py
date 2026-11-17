"""One-time administrator-only import; does not copy pages or translation files."""
import argparse
import sqlite3
from pathlib import Path
from database.store import Store


def migrate(source_path, destination_path):
    source, destination = Path(source_path).resolve(), Path(destination_path).resolve()
    if source == destination or not source.is_file():
        raise ValueError('Укажите существующую исходную БД и другую серверную БД.')
    connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('BEGIN')
        invites = connection.execute('SELECT code,created_at FROM invites').fetchall()
        users = connection.execute('SELECT id,login,invite,hwid,created_at FROM users').fetchall()
        requests = connection.execute('SELECT id,user_id,new_hwid,reason,status,created_at FROM hardware_requests').fetchall()
    finally:
        connection.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    store = Store(destination)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone() or db.execute('SELECT 1 FROM invites LIMIT 1').fetchone():
            raise ValueError('Серверная БД уже содержит данные. Импорт в неё запрещён.')
        db.executemany('INSERT INTO invites(code,created_at) VALUES (?,?)', invites)
        db.executemany('INSERT INTO users(id,login,invite,hwid,created_at) VALUES (?,?,?,?,?)', users)
        db.executemany('INSERT INTO hardware_requests(id,user_id,new_hwid,reason,status,created_at) VALUES (?,?,?,?,?,?)', requests)
    return len(users), len(invites)


def main():
    parser = argparse.ArgumentParser(description='Перенос прежних инвайтов в серверную БД; запускать с выключенным приложением')
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', default='server/data/auth.db')
    args = parser.parse_args()
    try:
        users, invites = migrate(args.source, args.destination)
        print(f'Перенесено пользователей: {users}, инвайтов: {invites}. История осталась в исходной БД.')
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'Ошибка: {exc}\n')


if __name__ == '__main__':
    main()
