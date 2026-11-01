# Stage 1: Build the Vue app
FROM node:20-alpine AS build

WORKDIR /app

# Cap Node.js heap to avoid OOM on low-memory machines
ENV NODE_OPTIONS="--max-old-space-size=512"

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:stable-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
