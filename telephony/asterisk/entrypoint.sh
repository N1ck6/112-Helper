#!/bin/sh
# Зачем этот скрипт вообще нужен:
#  Поэтому:
#   1) конфиги в /etc/asterisk-templates лежат с плейсхолдерами вида
#      ${AMI_PASSWORD};
#   2) при старте контейнера entrypoint прогоняет их через envsubst,
#      подставляя реальные значения из .env (docker-compose передаёт
#      их как ENV контейнера);
#   3) результат кладётся в /etc/asterisk — оттуда их уже читает сам
#      Asterisk.
set -e

TEMPLATE_DIR=/etc/asterisk-templates
TARGET_DIR=/etc/asterisk

mkdir -p "$TARGET_DIR"

for f in "$TEMPLATE_DIR"/*.conf; do
    name=$(basename "$f")
    envsubst < "$f" > "$TARGET_DIR/$name"
done

mkdir -p /var/log/asterisk /var/spool/asterisk/monitor /recordings
chown -R asterisk:asterisk /var/log/asterisk /var/spool/asterisk /recordings 2>/dev/null || true

exec "$@"
