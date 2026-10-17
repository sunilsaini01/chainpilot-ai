# The dashboard as a container: build the static files with Node, serve them with nginx.
# The API address is baked in at build time (Vite replaces import.meta.env.VITE_API_URL).

FROM node:24.21.0-alpine AS build
WORKDIR /app
# Dependencies first so this layer is cached when only the code changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.30.5-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Run as the unprivileged nginx user, like the API image: the pid file moves to /tmp
# and the cache folders become writable for that user. Port 8080 needs no root.
RUN sed -i 's,^pid .*,pid /tmp/nginx.pid;,' /etc/nginx/nginx.conf \
    && sed -i '/^user /d' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1:8080/ || exit 1
