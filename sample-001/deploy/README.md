# Local Delivery Contracts

These artifacts are review and validation contracts for SAMPLE-001. They do not authorize a deployment.

## Disposable Compose stack

From `sample-001/`, generate ignored local/demo credentials, then validate without starting containers:

```sh
python deploy/compose/generate-env.py
podman compose --env-file deploy/compose/.env.local -f deploy/compose/compose.yaml config
```

On Windows, use `py -3 deploy/compose/generate-env.py` if `python` opens the Microsoft Store alias.

`podman compose` requires a Compose provider on PATH, such as `podman-compose` or Docker Compose. Starting the stack is separately authorized local mutation. All published ports bind to loopback. `podman compose down --volumes` removes the disposable database and object volumes. Never use real documents or credentials.

Compose creates separate BFF, API, scanner, promotion, and deletion database logins from the ignored local environment file. The fake scanner receives only a read-only quarantine subpath; its `/objects/clean` path is an isolated empty tmpfs. The BFF retries fake-provider discovery for a bounded startup window and returns successful callbacks to the configured frontend origin.

The loopback service publishes only `127.0.0.1` host ports. Services that must be reachable through Docker/Podman port forwarding bind to `0.0.0.0` inside the shared container network namespace with `SAMPLE001_ALLOW_CONTAINER_WILDCARD_BIND=true` and `SAMPLE001_CONTAINER_RUNTIME=compose`. This is a local/demo-only exception so host access still remains loopback-only.

Some Docker Desktop and rootless Podman volume backends reject chmod/chown on named volume roots. The local compose stack therefore initializes object directories with `mkdir`, sets `SAMPLE001_ALLOW_RELAXED_STORAGE_PERMISSIONS=true` only for object-storage services, and overrides those local demo containers to run as root inside the container. The production-shaped images and Helm contract remain non-root. If an older failed run created the object volume with incompatible metadata, remove the disposable volume before retrying:

```powershell
podman volume rm sample-001_objects
```

PostgreSQL 18 stores data under a major-version-specific subdirectory. The compose volume is mounted at `/var/lib/postgresql`, not `/var/lib/postgresql/data`. If an older partial run created the disposable database volume with the old layout, remove it before retrying:

```powershell
podman volume rm sample-001_postgres-data
```

If Compose reports that `sample-001_backend` has an incorrect `com.docker.compose.network` label, remove the stale stopped demo containers and network before retrying:

```powershell
$ids = @(podman ps -a --filter label=com.docker.compose.project=sample-001 -q)
if ($ids.Count -gt 0) { podman rm -f $ids }
podman network rm sample-001_backend
```

The equivalent shell form is:

```sh
podman ps -a --filter label=com.docker.compose.project=sample-001 -q | xargs -r podman rm -f
podman network rm sample-001_backend
```

## Render-only Helm chart

The chart excludes fake identity, fake scanning, PostgreSQL, migrations, hooks, CRDs, and cluster-scoped resources. It references an externally managed secret and requires digest-pinned images. Render with non-secret review values only:

```sh
helm lint deploy/helm/sample-001 -f deploy/helm/sample-001/ci/render-values.yaml
helm template sample-001 deploy/helm/sample-001 -n sample-001 -f deploy/helm/sample-001/ci/render-values.yaml
```

The rendered output is not installable until production decisions DEC-001–009, real integrations, secret delivery, policies, and human gates are approved. Do not run `helm install` or `helm upgrade` for this demo.

## Local contract tests

Run `python -B -m unittest discover -s deploy/tests -p "test_*.py"`. Helm, Terraform, and Podman-native validations require the pinned tools on a disposable runner.
