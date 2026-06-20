FROM node:22-alpine
WORKDIR /app
COPY package.json package.json
COPY src src
COPY fixtures fixtures
COPY test test
ENV SIGNAL_LAYER_HOST=0.0.0.0
ENV SIGNAL_LAYER_PORT=8787
EXPOSE 8787
CMD ["node", "src/index.mjs"]
