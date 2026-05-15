# QUICKSTART — первый запуск с новой авторизацией (Phase 2)

После Phase 2 регистрация через email+пароль убрана. Вход — **email-код** (отправка через Resend) или один из 4 OAuth-провайдеров (Google, Yandex, GitHub, Telegram).

---

## A. На прод-сервере

После push в `main` GitHub Actions сам соберёт три образа в GHCR и задеплоит на сервер. Чтобы это заработало в первый раз — настрой секреты и сторонние сервисы.

### 1. GitHub Secrets

Уже должно быть (Phase 0):
`DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`, `BACKEND_DATABASE_URL`, `BACKEND_REDIS_URL`, `BACKEND_JWT_SECRET`, `BACKEND_ENCRYPTION_KEY`, `BACKEND_CORS_ORIGINS`, `BACKEND_LOG_LEVEL`.

**Добавить для Phase 2:**

| Secret | Что в нём | Где взять |
|---|---|---|
| `BACKEND_FRONTEND_URL` | `https://crypto.shilkaphilosophy.ru` | твой домен фронта |
| `VITE_API_URL` | `https://crypto.shilkaphilosophy.ru/api/` | публичный URL бэка |
| `VITE_WS_URL` | `wss://crypto.shilkaphilosophy.ru/ws/updates` | публичный WS |
| `HCAPTCHA_SITEKEY` | публичный sitekey | hCaptcha dashboard |
| `HCAPTCHA_SECRET` | серверный секрет | там же |
| `RESEND_API_KEY` | API key | https://resend.com/api-keys |
| `RESEND_SENDER_EMAIL` | `noreply@crypto.shilkaphilosophy.ru` | домен должен быть верифицирован в Resend |
| `RESEND_SENDER_NAME` | `Crypto Dashboard` | произвольно |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | OAuth | Google Cloud Console |
| `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI` | OAuth | https://oauth.yandex.ru/ |
| `GH_CLIENT_ID`, `GH_CLIENT_SECRET`, `GH_REDIRECT_URI` | OAuth | https://github.com/settings/developers |
| `TELEGRAM_BOT_TOKEN` | токен бота | @BotFather |
| `TELEGRAM_BOT_USERNAME` | `crypto_dashboard_kurs_bot` | имя бота без @ |

### 2. Действия в сторонних сервисах

- **Resend:** залогинься, добавь домен `crypto.shilkaphilosophy.ru`, пройди DKIM/SPF верификацию. Создай API key.
- **@BotFather (Telegram):**
  1. `/setdomain` → выбери `@crypto_dashboard_kurs_bot` → введи `crypto.shilkaphilosophy.ru`. Без этого виджет на проде вернёт «origin not allowed».
- **Google Cloud Console / Yandex OAuth / GitHub OAuth App:** в каждом из них убедись, что redirect URI **точно совпадает** с одноимённым `*_REDIRECT_URI` секретом (с `https://`, без trailing slash).

### 3. Push и деплой

```bash
# Из корня crypto-dashboard локально:
git push origin main
```

GitHub Actions:
- Соберёт три образа: backend, frontend (с вшитым `VITE_HCAPTCHA_SITEKEY`), engine.
- Зальёт по SSH, перепишет `.env`, прогонит миграции (включая `0002_oauth_identities` — TRUNCATE users + новая таблица), поднимет всё.

Проверка:
```bash
ssh -p <port> <user>@<host> 'docker compose -f /docker/crypto-dashboard/docker-compose.yml ps'
# должны быть Up healthy: crypto-backend, crypto-engine, crypto-frontend
```

### 4. Открой фронт

`https://crypto.shilkaphilosophy.ru` → редиректит на `/login`. Карточка с 4 круглыми соц-кнопками + email-форма с hCaptcha.

---

## B. Локально (Docker)

### 1. Заполни `.env`

```bash
cp .env.example .env  # gitignored
# Открой .env и заполни обязательные:
#   - BACKEND_JWT_SECRET, BACKEND_ENCRYPTION_KEY (сгенерировать через python -c)
#   - ENGINE_ENCRYPTION_KEY = BACKEND_ENCRYPTION_KEY (одинаковые!)
#   - RESEND_API_KEY + RESEND_SENDER_EMAIL (если хочешь реально получать письма)
#   - VITE_HCAPTCHA_SITEKEY + HCAPTCHA_SECRET (если хочешь реально проверять капчу)
# Локально можно отключить капчу через BACKEND_CAPTCHA_DISABLED=true.
```

Сгенерировать новые секреты:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"        # JWT
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # Fernet
```

### 2. Поднять весь стек

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

Что поднимется:
- `crypto-db` (Postgres), `crypto-redis`, `crypto-backend`, `crypto-frontend`, `crypto-engine`.
- `migrate` прогонит 0001 и 0002 миграции.

### 3. Проверь

```bash
curl http://localhost:8000/healthz   # → {"backend":"ok","postgres":"ok","redis":"ok"}
docker compose ps                     # все Up healthy
```

Открой фронт: http://localhost:5173

---

## C. Flow логина в UI

### Email + код
1. На `/login` введи email → нажми «Отправить код».
2. На указанный адрес придёт письмо от Resend с 6-значным кодом (~10 секунд).
3. Введи код в поле → «Войти». Аккаунт создаётся автоматически при первом входе.

### Через OAuth (Google/Yandex/GitHub)
1. Кликни круглую иконку.
2. Браузер уйдёт к провайдеру → подтверждение → вернётся на `/auth/callback?access=...&refresh=...`.
3. Фронт извлечёт токены и редиректнёт на `/`.

### Через Telegram
1. Кликни голубую иконку.
2. Откроется попап Telegram → авторизация.
3. Telegram передаст данные обратно через JS callback → бэк проверит HMAC → выдаст JWT.

### Дальше
- **Settings** → добавь Binance Testnet API ключи.
- **Strategies** → «Создать стратегию» → SmaCross BTC/USDT 1m → «Сохранить и запустить».

---

## Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| Email не приходит | `RESEND_API_KEY` пустой / домен не верифицирован | Проверь .env и dashboard Resend |
| `400 captcha rejected` | `HCAPTCHA_SECRET` не совпадает с sitekey | Перепроверь оба ключа в hCaptcha dashboard |
| `503 OAuth provider not configured` | пустые `*_CLIENT_ID/SECRET/REDIRECT_URI` | Добавь секреты в env |
| Telegram-виджет: «origin not allowed» | в @BotFather домен не установлен | `/setdomain` для бота |
| Логин Google → "redirect_uri_mismatch" | URI в Google Console не совпадает с `GOOGLE_REDIRECT_URI` | Подгони — обычно различия в `https://` или trailing `/` |
| `429 too many code requests` | Rate limit на IP — 3 запроса в минуту | Подожди 1 минуту |
| `429 too many wrong attempts` | 5 неверных кодов — ключ удалён | Запроси новый код |

---

## Известные ограничения (Phase 2)

- Токены лежат в localStorage (XSS-vulnerable). HttpOnly cookies — Phase 3+.
- Нет 2FA / TOTP.
- Нет восстановления через email при потере OAuth (но если у пользователя есть тот же email — он попадёт в свой аккаунт через email-код, identity_service сам слинкует).
- Нет blacklist'а refresh-токенов.
