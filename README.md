# Medical Navigator (MVP)

Монолит: **FastAPI** (REST + серверные дашборды) и небольшие **JS-скрипты** для публичных страниц.

## Запуск
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env            # необязательно: без DATABASE_URL работает SQLite
python -m app.seed              # демо-данные (вымышленные)
uvicorn app.main:app --reload   # http://localhost:8000  ·  Swagger: /docs
```
Переменные из `.env` нужно экспортировать в окружение (или запускать через `uvicorn --env-file .env`).
Для PostgreSQL: `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db`. Таблицы создаются автоматически (`create_all`), новая таблица одна — `clinic_images`.

## Демо-аккаунты (пароль `Demo12345!`)
| Роль | Email | Страница |
|---|---|---|
| Пациент | patient@demo.test | /dashboard |
| Координатор | coord@demo.test | /coordinator |
| Клиника (Дели) | clinic1@demo.test | /clinic |
| Клиника (Стамбул) | clinic2@demo.test | /clinic |
| Админ | admin@demo.test | /admin, /admin/moderation |

## Кто за что отвечает
- **FastAPI, работа с БД:** `app/routers/api.py` (43 эндпоинта /api/v1), `app/routers/pages.py` (дашборды пациента, координатора, клиники, админка, модерация), `app/services.py` (правила: статусы, согласия, доступ, метрики).
- **JS (`frontend/js`):** каталог и карточка клиники, вход/регистрация, форма заявки с файлами, чат. Они только вызывают REST API.

## Картинки из облака
В таблице `clinic_images` лежит полный `https://…` или ключ объекта (`clinics/a.jpg`). Для ключа задайте `CLOUD_MEDIA_BASE_URL` (публичный бакет Supabase / S3 / R2 / Cloudinary). Админ меняет картинку в `/admin` (поле «URL или ключ»). Если файл недоступен, показывается заглушка с буквой.

## Безопасность (кратко)
Argon2, JWT (15 мин) + HttpOnly refresh-cookie; cookie-сессия принимается API только для GET; доступ к кейсам и файлам считается на сервере по владельцу, роли и согласию; проверка размера, MIME и сигнатуры файла; аудит согласий и действий с файлами.

## Тесты
`cd backend && pytest` — сквозной сценарий (AC-01…AC-07) и негативные проверки доступа.

## Не вошло
Alembic-миграции, уведомления по email, модерация сообщений (нужен флаг `is_hidden` в `messages`).
