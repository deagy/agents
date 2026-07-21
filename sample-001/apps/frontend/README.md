# SAMPLE-001 Frontend

This React/TypeScript application is a local demonstration, not a production client. It uses same-origin BFF endpoints, keeps the CSRF token and document state only in memory, and never previews uploaded content.

## Development

Use the pinned Node 24.18.0 and npm 12.0.1 versions:

```sh
npm ci
npm run typecheck
npm test
npm run build
npm run test:e2e
```

The Vite server binds to `127.0.0.1:5173` and proxies `/auth` and `/api` to the local BFF at `127.0.0.1:8080`. Production builds disable source maps.

## Browser/API contract

- `GET /api/v1/session` returns `{authenticated:false}` or an authenticated response with `csrf_token` and `user.display_name`.
- Uploads send multipart `FormData` field `file`, `X-CSRF-Token`, and a stable `Idempotency-Key` reused on retry.
- Document responses use `{document:{id,name,status,message?}}`.
- Only a `clean` document renders a download link. Deletion requires confirmation and is polled until the owner-scoped document returns `404`.

Playwright targets Chromium, Firefox, and WebKit. Install the matching browser binaries in a disposable test runner before executing end-to-end tests.
