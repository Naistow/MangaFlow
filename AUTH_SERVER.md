## Локальная проверка на Windows

Из корня проекта, рабочим Python 3.11+:

```powershell
python -m venv .venv-auth
.\.venv-auth\Scripts\python.exe -m pip install -r server/requirements.txt
```

Импорт не переносит историю страниц и не перезаписывает заполненную серверную базу.
Вместо импорта можно начать с новых кодов:

```powershell
.\.venv-auth\Scripts\python.exe admin_invites.py generate --count 1
.\.venv-auth\Scripts\python.exe -m uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Для локальной проверки добавьте в `.env` клиента:

```dotenv
MF_AUTH_SERVER_URL=http://127.0.0.1:8000
MF_AUTH_ALLOW_LOCAL_HTTP=1
должна требовать серверный ресурс — это уже меняет архитектуру локального перевода.
