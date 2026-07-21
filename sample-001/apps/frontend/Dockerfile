# syntax=docker/dockerfile:1.7
FROM node:24.18.0-alpine3.23@sha256:595398b0081eacda8e1c4c5b97b76cd1020e4d58a8ebcb4843b9bca1e79e7436 AS development
WORKDIR /workspace
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts && test "$(node node_modules/npm/bin/npm-cli.js --version)" = "12.0.1"
COPY . .
EXPOSE 5173
CMD ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--configLoader", "runner"]

FROM development AS build
RUN node node_modules/typescript/bin/tsc -b && node node_modules/vite/bin/vite.js build

FROM nginxinc/nginx-unprivileged:1.29.5-alpine3.23@sha256:42a7d7f2ee23e9f5a1dcdf3647ba5c585bbd18f79e79cd817e70e8cd61c55779 AS demo
COPY --from=build /workspace/dist /usr/share/nginx/html
USER 101
EXPOSE 8080

FROM nginxinc/nginx-unprivileged:1.29.5-alpine3.23@sha256:42a7d7f2ee23e9f5a1dcdf3647ba5c585bbd18f79e79cd817e70e8cd61c55779 AS demo-prebuilt
COPY dist /usr/share/nginx/html
USER 101
EXPOSE 8080
