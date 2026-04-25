FROM ngrok/ngrok:3-alpine

USER root
RUN apk add --no-cache bash grep curl ca-certificates

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
