# The web front: the built React app, served by Caddy, which also gets the HTTPS certificate and passes the API to the
# app container. Built from the repository root:  docker build -f deploy/web.Dockerfile .
FROM node:24-slim AS build
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ .
ARG VITE_PLATFORM_NAME=""
ENV VITE_PLATFORM_NAME=${VITE_PLATFORM_NAME}
RUN npm run build

FROM caddy:2.10-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /client/dist /srv
