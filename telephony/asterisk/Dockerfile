FROM ubuntu:24.04


RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository -y universe \
    && apt-get update


RUN apt-get install -y --no-install-recommends \
        asterisk \
        asterisk-core-sounds-en \
        ffmpeg \
        curl \
        netcat-openbsd \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

    
RUN mkdir -p /var/log/asterisk /var/spool/asterisk /recordings \
    && chown -R asterisk:asterisk /var/log/asterisk /var/spool/asterisk /recordings

COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/healthcheck.sh /usr/local/bin/entrypoint.sh

EXPOSE 5060/udp 5060/tcp 5038/tcp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# -f = foreground (не демонизировать, чтобы Docker видел процесс и логи)
# -vvv = уровень verbose-логов в консоль (docker logs)
CMD ["asterisk", "-f", "-vvv"]
