# Мониторинг Mektep Platform

## UptimeRobot
- URL: `https://mektep-analyzer.kz/health/live`
- Интервал: 5 минут
- В Cloudflare: Cache Level = Bypass для `/health/*`

## Prometheus

**URL:** http://localhost:9090

Порт 9090 проброшен в `docker-compose.yml`. После `docker-compose up -d` откройте в браузере.

## Grafana

**URL:** http://localhost:3000

Порт 3000 уже проброшен в `docker-compose.yml`.

- **Логин:** admin
- **Пароль:** значение `GRAFANA_ADMIN_PASSWORD` (по умолчанию: `admin`)

**Первый вход:**
1. Откройте http://localhost:3000
2. Войдите (admin / admin)
3. **Connections** → **Data sources** → **Add data source**
4. Выберите **Prometheus**
5. **URL:** `http://prometheus:9090` → **Save & test**
