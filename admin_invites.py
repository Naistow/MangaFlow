"""Run only on the trusted administrator's copy of the database."""
import argparse
import sqlite3
import os
from pathlib import Path
from core.auth import AuthService, AuthError
from database.store import Store


def main():
    parser = argparse.ArgumentParser(description='MangaFlow: запускать на сервере администратора')
    parser.add_argument('--db', default=os.getenv('MF_AUTH_DB', 'server/data/auth.db'), help='Серверная БД авторизации')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('generate').add_argument('--count', type=int, default=1)
    for name in ('users', 'invites', 'requests'):
        sub.add_parser(name)
    for name in ('approve', 'reject'):
        sub.add_parser(name).add_argument('id', type=int)
    for name in ('unbind', 'delete'):
        sub.add_parser(name).add_argument('code')
    args = parser.parse_args()
    try:
        path = Path(args.db).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        auth = AuthService(Store(path))
        if args.command == 'generate':
            print('\n'.join(auth.generate_invites(args.count)))
        elif args.command in ('approve', 'reject'):
            auth.review_reset(args.id, args.command == 'approve')
            print('Заявка обработана.')
        elif args.command in ('unbind', 'delete'):
            auth.manage_invite(args.code, args.command == 'delete')
            print('Инвайт обновлён.')
        else:
            queries = {
                'users': 'SELECT * FROM users',
                'invites': 'SELECT i.*,u.login,u.hwid FROM invites i LEFT JOIN users u ON u.invite=i.code',
                'requests': 'SELECT r.*,u.login FROM hardware_requests r JOIN users u ON u.id=r.user_id ORDER BY r.id DESC',
            }
            with auth.store.connect() as db:
                for row in db.execute(queries[args.command]):
                    print(dict(row))
    except (AuthError, sqlite3.Error, OSError) as exc:
        parser.exit(1, f'Ошибка: {exc}\n')


if __name__ == '__main__':
    main()
