# Готовые конфигурации запуска для PyCharm

Семь кнопок в панели запуска: сервер, тесты, миграции, стартовые данные, линтер,
настройка окружения и проверка комплекса.

Папка `.idea` в `.gitignore` — настройки IDE у каждого свои, поэтому конфигурации
лежат здесь и копируются одной командой:

```powershell
xcopy /E /I /Y docs\pycharm\runConfigurations .idea\runConfigurations
```

На Linux и macOS:

```bash
mkdir -p .idea/runConfigurations && cp docs/pycharm/runConfigurations/*.xml .idea/runConfigurations/
```

После копирования PyCharm подхватывает их сам — обычно сразу, иногда после
**File → Reload All from Disk**.

Инструкция по запуску — [`../PYCHARM.md`](../PYCHARM.md).
