# Local Delivery Contracts

These artifacts are review and validation contracts for SAMPLE-001. They do not authorize a deployment.

## Disposable Compose stack

Copy `.env.example` to the ignored `.env.local`, replace every `CHANGE_ME` value, and validate without starting containers:

```sh
podman compose --env-file deploy/compose/.env.local -f deploy/compose/compose.yaml config
```

Starting the stack is separately authorized local mutation. All published ports bind to loopback. `podman compose down --volumes` removes the disposable database and object volumes. Never use real documents or credentials.

Compose creates separate BFF, API, scanner, promotion, and deletion database logins from the ignored local environment file. The fake scanner receives only a read-only quarantine subpath; its `/objects/clean` path is an isolated empty tmpfs. The BFF retries fake-provider discovery for a bounded startup window and returns successful callbacks to the configured frontend origin.

## Render-only Helm chart

The chart excludes fake identity, fake scanning, PostgreSQL, migrations, hooks, CRDs, and cluster-scoped resources. It references an externally managed secret and requires digest-pinned images. Render with non-secret review values only:

```sh
helm lint deploy/helm/sample-001 -f deploy/helm/sample-001/ci/render-values.yaml
helm template sample-001 deploy/helm/sample-001 -n sample-001 -f deploy/helm/sample-001/ci/render-values.yaml
```

The rendered output is not installable until production decisions DEC-001–009, real integrations, secret delivery, policies, and human gates are approved. Do not run `helm install` or `helm upgrade` for this demo.

## Local contract tests

Run `python -B -m unittest discover -s deploy/tests -p "test_*.py"`. Helm, Terraform, and Podman-native validations require the pinned tools on a disposable runner.
