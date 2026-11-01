FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
ARG VITE_BASE=/
ARG VITE_API_BASE=
ENV VITE_BASE=$VITE_BASE VITE_API_BASE=$VITE_API_BASE
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
