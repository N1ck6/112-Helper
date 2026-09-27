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
    envsubst '${AMI_PASSWORD} ${SIP_ALICE_PASSWORD} ${SIP_BOB_PASSWORD} ${EXTERNAL_MEDIA_ADDRESS} ${EXTERNAL_SIGNALING_PORT}' \
        < "$f" > "$TARGET_DIR/$name"
done

# Учётные записи рабочих мест обучающихся: ws01..wsNN (TRAINEE_ACCOUNTS),
# общий пароль класса TRAINEE_PASSWORD. Генерируются, чтобы не держать в
# pjsip.conf 20+ одинаковых блоков; alice/bob остаются для ручных тестов.
if [ "${TRAINEE_ACCOUNTS:-0}" -gt 0 ]; then
    i=1
    while [ "$i" -le "$TRAINEE_ACCOUNTS" ]; do
        ws=$(printf "ws%02d" "$i")
        printf '\n[%s]\ntype = endpoint\ncontext = internal\ndisallow = all\nallow = ulaw,alaw\nauth = %s-auth\naors = %s\ncallerid = "Workplace %s" <%s>\ndirect_media = no\nrtp_symmetric = yes\nforce_rport = yes\nrewrite_contact = yes\nmedia_use_received_transport = yes\n' "$ws" "$ws" "$ws" "$i" "$ws" >> "$TARGET_DIR/pjsip.conf"
        printf '\n[%s-auth]\ntype = auth\nauth_type = userpass\nusername = %s\npassword = %s\n' "$ws" "$ws" "${TRAINEE_PASSWORD:-changeme_ws}" >> "$TARGET_DIR/pjsip.conf"
        printf '\n[%s]\ntype = aor\nmax_contacts = 1\nremove_existing = yes\n' "$ws" >> "$TARGET_DIR/pjsip.conf"
        i=$((i + 1))
    done
fi

mkdir -p /var/log/asterisk /var/spool/asterisk/monitor /recordings
chown -R asterisk:asterisk /var/log/asterisk /var/spool/asterisk /recordings 2>/dev/null || true

exec "$@"
