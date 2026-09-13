# Two targets:
#   development — Vite dev server with hot reload (used by docker compose)
#   production  — static build served by nginx

FROM node:22-alpine AS development

WORKDIR /app

# Copy manifests first so `npm ci` is cached and only re-runs when deps change.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


FROM node:22-alpine AS build

WORKDIR /app

# Vite bakes VITE_-prefixed vars into the bundle at build time, normally from
# a .env.production file — but .dockerignore excludes .env* from ever
# reaching this build context (correctly, since most .env files carry real
# secrets), which silently left this one build-time-only, no-secret value
# unset and falling back to api/client.ts's local-dev default
# (http://localhost:8000/api/v1) in every image built here. A build ARG sinks
# below .dockerignore entirely, so it's the only mechanism here that actually
# reaches the build. See docker-compose.prod.yml for the real value.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build


FROM nginx:alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
