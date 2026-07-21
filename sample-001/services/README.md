# Go Services

This single Go module builds the local BFF, document API, fake OIDC provider, fake scanner, promotion, deletion, and reconciliation commands. Every command requires explicit `SAMPLE001_MODE=development` or `test` when it uses a development adapter. The fake scanner and fake OIDC images have only explicitly fake/development targets; Helm must reference approved external implementations.

Run the non-service checks from this directory:

```powershell
$env:GOTOOLCHAIN = 'local'
go mod verify
$gofmt = gofmt -l .
if ($gofmt) { $gofmt; throw 'run gofmt -w .' }
$goimports = go tool goimports -l .
if ($goimports) { $goimports; throw 'run go tool goimports -w .' }
go test ./...
go vet ./...
go tool golangci-lint run ./...
```

`go test ./...` executes unit, security-boundary, filesystem, and Godog contract scenarios; database-backed integration tests skip unless `SAMPLE001_TEST_DATABASE_URL` names a migrated disposable database. CI exercises real fake-OIDC redirects, BFF/API HTTP, PostgreSQL sessions and role denials, filesystem storage, scanner, promotion, and clean download. A prepared disposable Linux runner must additionally run `go test -race ./...` and the real-browser matrix. Those validations are not replaced by the in-process Godog contract suite.

Tooling is pinned in `go.mod`: `gofmt` comes from the Go 1.26.5 toolchain, while `goimports` and `golangci-lint` run through `go tool` so local and CI checks use the same reviewed versions.

Uploads are limited to four concurrent requests per API process, 20 non-deleted documents and 250 MiB per owner, and 25 MiB per file. Worker filesystem actions hold PostgreSQL job and document row locks through the exact-version operation and job completion. Use only synthetic files; the EICAR adapter is not malware protection.

For deterministic failure-path testing only, set `SAMPLE001_SCANNER_FAILURE_SHA256` on the fake scanner to the exact lowercase SHA-256 of a synthetic fixture. The scanner will fail that object through the normal bounded retry/dead-job path. The setting is rejected for non-scanner services and does not exist in Helm.
