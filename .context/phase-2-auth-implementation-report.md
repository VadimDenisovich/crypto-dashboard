# Phase 2 — отчёт о реализации (Auth: Identity Providers)

Этот файл описывает простым языком, что было сделано в рамках Phase 2 ROADMAP'а — переход с email+пароль аутентификации на email-код (через Resend) + OAuth (Google/Yandex/GitHub/Telegram) + hCaptcha. Также обновлён фавикон и title сайта.

---

## Кратко: «было» vs «стало»

**Было:**
- На фронте: страницы `/login` и `/register` с формами email + пароль (минимальный дизайн, MUI Card 420px).
- На бэке: `POST /auth/register`, `POST /auth/login` с bcrypt-хэшем, `password_hash` в БД (NOT NULL).
- Фавикон не подключен; title `Макет сайта на React`.

**Стало:**
- На фронте: одна страница `/login` с 4 круглыми соц-кнопками (Google/Yandex/Telegram/GitHub) + email-форма с hCaptcha → 6-значный код. По дизайну — отсылает к референсу [vadim-denisovich.ru/login](https://vadim-denisovich.ru/login), но в нашей dark-палитре.
- Регистрация **автоматическая** при первом входе любым способом.
- На бэке: пароль-логин полностью убран. Есть `POST /auth/email/request|verify`, `POST /auth/refresh`, `GET /auth/me`, `GET /api/auth/{provider}/start|callback`, `GET/POST /api/auth/telegram/widget-config|verify`.
- Новая таблица `oauth_identities` (UNIQUE provider+subject) для привязок к провайдерам.
- Title: `Crypto Dashboard`. Фавикон — иконка из `sources/favicon.png`.

**Существующие пользователи** (тестовые dev/prod) **сброшены** — миграция 0002 делает `TRUNCATE users CASCADE`. Все ордера/боты/креды тоже зачищены.

---

## 1. Backend (submodule `crypto-dashboard-backend`, коммит `85c4910`)

### 1.1. БД-миграция `0002_oauth_identities.py`
- TRUNCATE users CASCADE (зачищает users + всё что от них зависит каскадно: bots, exchange_credentials, orders, trades, balance_snapshots, strategy_errors, bot_commands).
- `users.password_hash` → nullable.
- Новые колонки `users.updated_at` и `users.last_login_at`.
- Новая таблица `oauth_identities (id, user_id, provider, subject, email, created_at)` с уникальным индексом `(provider, subject)`.

### 1.2. Email + код через Resend
- `infrastructure/captcha.py` — POST `https://api.hcaptcha.com/siteverify`. Можно отключить через `BACKEND_CAPTCHA_DISABLED=true` (для CI/локалки).
- `infrastructure/resend_email.py` — клиент через httpx, POST `https://api.resend.com/emails`. Тёмное HTML-письмо с большими цифрами кода, helper `build_code_email(code) → (subject, html, text)`.
- `infrastructure/email_codes.py` — `EmailCodeStore` на Redis: 6-значный код, bcrypt-хэш в Redis с TTL 600 сек, attempts counter (макс 5 → ключ удаляется), IP rate-limit 3/мин через `INCR + EXPIRE`.
- `services/email_auth_service.py` — оркестрирует request/verify, под капотом вызывает captcha + codes + Resend.

### 1.3. OAuth Google/Yandex/GitHub
- `infrastructure/oauth_clients.py`:
  - `ProviderConfig` для каждого провайдера (authorize/token/userinfo URL, scope).
  - GitHub использует `client_secret_post`, Google — `access_type=offline + prompt=select_account`.
  - `issue_state(redis, provider)` / `consume_state(redis, state)` — CSRF state в Redis на 10 мин (one-shot, удаляется при первом consume).
  - `exchange_code_for_token(cfg, code)` через `authlib.AsyncOAuth2Client`.
  - `fetch_userinfo(cfg, access_token)` — у Google и GitHub Bearer, у Yandex `OAuth <token>`. У GitHub если email скрыт — добор через `/user/emails`.
- `api/routers/oauth.py`:
  - `GET /api/auth/{provider}/start` — 302 на провайдера.
  - `GET /api/auth/{provider}/callback` — обмен → userinfo → resolve_or_create_user → выпуск JWT → 302 на `BACKEND_FRONTEND_URL/auth/callback?access=…&refresh=…`.

### 1.4. Telegram Login Widget
- `infrastructure/telegram_auth.py` — `verify_telegram_login(payload, bot_token, max_age_sec)`:
  - HMAC-SHA256: `secret = sha256(bot_token).digest()`; data_check_string из всех полей кроме hash, отсортированных; `hmac.compare_digest(...)`.
  - Проверка `auth_date` ≤ 24 часа.
  - 6 unit-тестов покрывают валидный/невалидный hash, старый auth_date, отсутствующий hash/bot_token, не-латинские поля.
- `api/routers/oauth.py`:
  - `GET /api/auth/telegram/widget-config` → `{bot_username}`.
  - `POST /api/auth/telegram/verify` — проверка HMAC → resolve user → JSON с JWT (для Telegram redirect не нужен — widget callback в JS).

### 1.5. `services/identity_service.py`
- `resolve_or_create(provider, subject, email)`:
  1. Найти existing identity по `(provider, subject)` → существующий user.
  2. Иначе если есть email — найти user по email и привязать identity.
  3. Иначе создать user (с email или synthetic `telegram-{id}@telegram.local`).
  4. Создать identity, обновить `last_login_at`.

### 1.6. Изменения в `auth_service.py`
- Удалены `register()` и `login()` (password flow).
- Оставлены `refresh()` и `_issue_tokens()`. Добавлен публичный синоним `issue_tokens()` для использования из других сервисов (email_auth, oauth, telegram).

### 1.7. Settings (`config.py`)
17 новых полей: `backend_frontend_url`, `backend_captcha_disabled`, `hcaptcha_secret`, `resend_*` (3), `google_*` (3), `yandex_*` (3), `gh_*` (3), `telegram_bot_token`, `telegram_bot_username`, `backend_telegram_auth_max_age_sec`, `backend_email_*` (3 — TTL/attempts/rate-limit).

### 1.8. Lifespan (`main.py`)
- В `app.state` добавлены `resend: ResendClient` и `email_codes: EmailCodeStore`.
- Подключён router `oauth.router`.
- Добавлена deps-функция `get_redis/get_resend/get_email_codes` в `api/deps.py`.

### 1.9. Schemas
- `api/schemas/auth.py` — удалены `RegisterIn`/`LoginIn`. Остались `RefreshIn`, `TokenOut`, `UserOut`.
- `api/schemas/email_auth.py` — `EmailRequestIn{email, captcha_token}`, `EmailRequestOut{status}`, `EmailVerifyIn{email, code: 6 цифр}`.
- `api/schemas/oauth.py` — `TelegramLoginIn`, `TelegramWidgetConfigOut`.

### 1.10. Тесты
- `tests/unit/test_telegram_hmac.py` (6 тестов): валидная подпись, неверный hash, старый auth_date, отсутствующий hash/bot_token, юникод-поля.
- `tests/unit/test_email_codes.py` (7 тестов): формат кода, issue+verify, lockout после max attempts, lower-case email, not-found, IP rate-limit, пустой IP.
- `tests/unit/test_oauth_state.py` (3 теста): roundtrip, one-shot consume, неизвестный state.
- **Итого новых тестов: 16. Полный suite — 24 passed.**
- Старые `test_security.py` сохранён.

### 1.11. Зависимости
- `authlib>=1.3` добавлен в `pyproject.toml` (httpx уже был).

---

## 2. Frontend (submodule `frontend`, коммит `9dc27b6`)

### 2.1. Удалено
- `src/app/pages/Register.tsx` — целиком.
- `register()` и `login()` из `auth/AuthContext.tsx` и `api/auth.ts`.
- Роут `/register` из `routes.tsx`.

### 2.2. Создано
- `src/app/pages/Login.tsx` — переписан с нуля. MUI Card 440px max, dark тема, 4 круглые соц-кнопки 56×56 с фирменными цветами:
  - Google: белый bg + цветная G
  - Яндекс: красный (#FC3F1D) + белая «Я»
  - Telegram: голубой (#26A5E4) + белый бумажный самолётик
  - GitHub: чёрный (#0d1117) + белый Octocat
- `src/app/pages/AuthCallback.tsx` — извлекает `access`/`refresh` из query string, вызывает `consumeCallbackTokens`, стирает токены из URL через `history.replaceState`, редиректит на `/`.
- `src/app/components/auth/SocialIcons.tsx` — 4 inline SVG (без npm deps).
- `src/app/components/auth/EmailCodeForm.tsx` — двух-шаговая форма:
  1. Email + hCaptcha (theme=dark) → «Отправить код».
  2. 6-цифровое поле с numeric inputmode → «Войти».
  - Resend cooldown 60 сек, кнопка «Отправить ещё раз».
- `src/app/components/auth/TelegramButton.tsx` — лениво подгружает `https://telegram.org/js/telegram-widget.js?22`, дёргает `Telegram.Login.auth({bot_id, request_access})` с username из `/api/auth/telegram/widget-config`.

### 2.3. AuthContext новые методы
- `requestCode(email, captchaToken)`
- `verifyCode(email, code)` — после успеха обновляет `user`
- `loginWithTelegram(payload)` — то же
- `consumeCallbackTokens(access, refresh)` — для `/auth/callback`
- `logout()` — без изменений
- Удалены: `login(email, password)`, `register(email, password)`

### 2.4. API client
- `requestEmailCode`, `verifyEmailCode`, `getTelegramWidgetConfig`, `loginWithTelegramPayload`, `consumeCallbackTokens`, `getOAuthStartUrl(provider)`.
- `me()` и `logout()` без изменений.
- `client.ts` (fetch wrapper + auto-refresh) не менялся.

### 2.5. index.html
- `<title>Crypto Dashboard</title>`
- `<link rel="icon" type="image/png" href="/favicon.png" />` + apple-touch-icon
- `<meta name="theme-color" content="#0b0e14">` (для browser chrome на мобильных)
- `lang="ru"`

### 2.6. public/favicon.png
- Скопирован из `sources/favicon.png` (PNG 334×334 RGBA, 51 КБ).

### 2.7. Dockerfile
- Добавлены build args `VITE_API_URL`, `VITE_WS_URL`, `VITE_HCAPTCHA_SITEKEY` → ENV перед `pnpm build`. Vite вшивает их в bundle.

### 2.8. .env.example
- Добавлен `VITE_HCAPTCHA_SITEKEY=43828046-3c52-4ae8-9d6e-c48cc45e79c2`.

### 2.9. Зависимости
- `@hcaptcha/react-hcaptcha ^1.11.0` (фактически 1.17.4 после lock'а).
- `pnpm-lock.yaml` обновлён.

### 2.10. Build
- `pnpm build` проходит без ошибок: 12312 модулей, 1.02 MB JS, 10 KB CSS.

---

## 3. Root (`crypto-dashboard`, коммит `<этот PR>`)

### 3.1. Изменено
- `docker-compose.yml` — в env `backend` сервиса добавлены 17 переменных Phase 2 (BACKEND_FRONTEND_URL, BACKEND_CAPTCHA_DISABLED, HCAPTCHA_SECRET, RESEND_*, *_CLIENT_ID/SECRET/REDIRECT_URI, TELEGRAM_*).
- `.github/workflows/deploy.yml`:
  - В `build & push frontend` шаге добавлены `build-args: VITE_API_URL/VITE_WS_URL/VITE_HCAPTCHA_SITEKEY`.
  - В `deploy` job — env: добавлены 17 новых secrets, `envs:` дополнен, `cat > .env <<EOF` пишет все новые переменные.
- `.env.example` — добавлен полный блок `=== Phase 2: identity providers ===` с подсказками про Resend/hCaptcha/OAuth.
- `scripts/seed_dev_setup.py` — заменён на заглушку, печатающую инструкцию «регистрация теперь через UI».
- `QUICKSTART.md` — переписан целиком: настройка GitHub Secrets, действия в Resend/@BotFather, локальный `.env`, flow логина в UI, troubleshooting.

### 3.2. Submodule pointers (bump)
- `backend` → `85c4910` (фича Phase 2)
- `frontend` → `9dc27b6` (фича Phase 2)
- `trade-engine-crypto` — без изменений (не трогали)

---

## 4. Секреты — что добавлено

### Уже существовали
`DEPLOY_SSH_*`, `BACKEND_DATABASE_URL`, `BACKEND_REDIS_URL`, `BACKEND_JWT_SECRET`, `BACKEND_ENCRYPTION_KEY`, `BACKEND_CORS_ORIGINS`, `BACKEND_LOG_LEVEL`.

### Добавлены пользователем
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`, `YANDEX_REDIRECT_URI`
- `GH_CLIENT_ID`, `GH_CLIENT_SECRET`, `GH_REDIRECT_URI`
- `TELEGRAM_BOT_TOKEN`
- `HCAPTCHA_SITEKEY`, `HCAPTCHA_SECRET`

### Нужны дополнительно (по итогу — пользователь должен добавить в GitHub Secrets)
- `BACKEND_FRONTEND_URL` = `https://crypto.shilkaphilosophy.ru`
- `VITE_API_URL` = `https://crypto.shilkaphilosophy.ru/api/`
- `VITE_WS_URL` = `wss://crypto.shilkaphilosophy.ru/ws/updates`
- `RESEND_API_KEY` = из https://resend.com/api-keys
- `RESEND_SENDER_EMAIL` = `noreply@crypto.shilkaphilosophy.ru` (домен должен быть верифицирован в Resend)
- `RESEND_SENDER_NAME` = `Crypto Dashboard`
- `TELEGRAM_BOT_USERNAME` = `crypto_dashboard_kurs_bot` (без @)

---

## 5. Действия в сторонних сервисах (что нужно сделать пользователю один раз)

1. **@BotFather** → `/setdomain` → выбрать `@crypto_dashboard_kurs_bot` → ввести `crypto.shilkaphilosophy.ru`. Иначе виджет на проде вернёт «origin not allowed».
2. **Resend** → добавить домен `crypto.shilkaphilosophy.ru`, пройти DKIM/SPF верификацию, создать API key.
3. **Google Cloud Console / Yandex OAuth / GitHub OAuth Apps** — проверить, что redirect URIs **точно совпадают** с `*_REDIRECT_URI` из секретов.

---

## 6. Известные ограничения (Phase 2)

- JWT в localStorage (XSS-vulnerable). HttpOnly cookies — отложено до Phase 3+.
- Нет 2FA / TOTP.
- Нет blacklist'а refresh-токенов (revocation).
- При утере OAuth — пользователь логинится тем же email через email-код, identity_service сам слинкует. Если email менялся (Telegram synthetic) — нет доступа.
- Rate limit на `/auth/email/verify` отсутствует (защита через max_attempts ≥ 5 → удаление ключа).
- Письмо письмо приходит с `Crypto Dashboard <noreply@…>` — для smtp-репутации желателен SPF + DKIM (делается в Resend dashboard при верификации домена).

---

## 7. Что НЕ сделано (отложено)

- 2FA/TOTP (на референсе был чекбокс «Подключить 2FA» — убрали как и было решено).
- Magic links вместо кода (оставили 6 цифр — проще UX).
- Подтверждение email при смене провайдера / unlinking identity.
- Recovery flow при потере доступа.

---

## 8. Команды-проверки на проде после деплоя

```bash
# 1. Все 3 контейнера живы
ssh -p 2244 vadim_denisovich@31.200.229.59 \
  'docker compose -f /docker/crypto-dashboard/docker-compose.yml ps'

# 2. Бэк отвечает
curl https://crypto.shilkaphilosophy.ru/healthz
# → {"backend":"ok","postgres":"ok","redis":"ok"}

# 3. Telegram widget config доступен
curl https://crypto.shilkaphilosophy.ru/api/auth/telegram/widget-config
# → {"bot_username":"crypto_dashboard_kurs_bot"}

# 4. OAuth start даёт 302 на провайдера
curl -I https://crypto.shilkaphilosophy.ru/api/auth/google/start
# → 302 Location: accounts.google.com/o/oauth2/v2/auth?...

# 5. Email request с пустым captcha → 400
curl -X POST https://crypto.shilkaphilosophy.ru/auth/email/request \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","captcha_token":""}'
# → 400 captcha token missing
```

После всего этого — открыть `/login` в браузере и пройти полный flow (email-код или OAuth).
