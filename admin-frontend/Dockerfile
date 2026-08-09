FROM node:22-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_USER_FRONTEND_URL=
ARG VITE_USER_FRONTEND_PORT=80
ENV VITE_USER_FRONTEND_URL=$VITE_USER_FRONTEND_URL
ENV VITE_USER_FRONTEND_PORT=$VITE_USER_FRONTEND_PORT
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
