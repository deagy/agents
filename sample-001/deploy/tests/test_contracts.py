from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "sample-001"


class DeliveryContractTests(unittest.TestCase):
    def test_compose_public_ports_are_loopback_only(self) -> None:
        text = (SAMPLE / "deploy/compose/compose.yaml").read_text(encoding="utf-8")
        published = re.findall(r'"([^"\n]+:\d+:\d+)"', text)
        self.assertTrue(published)
        self.assertTrue(all(value.startswith("127.0.0.1:") for value in published))
        self.assertIn("postgres:18.4-alpine3.23", text)
        self.assertNotIn("latest", text)

    def test_compose_uses_fail_closed_service_contract(self) -> None:
        text = (SAMPLE / "deploy/compose/compose.yaml").read_text(encoding="utf-8")
        for service in ("bff", "api", "promotion", "deletion", "reconciliation", "fake-oidc"):
            self.assertIn(f"target: {service}-development", text)
        self.assertIn("target: fake-scanner-development", text)
        self.assertIn("network_mode: service:loopback", text)
        self.assertIn("SAMPLE001_MODE: development", text)
        self.assertIn("objects-init:", text)
        self.assertNotIn("APP_ENV:", text)
        self.assertNotIn("SAMPLE001_DATABASE_URL: postgres://sample001:${POSTGRES_PASSWORD}", text)
        for role in ("bff", "api", "scanner", "promotion", "deletion"):
            self.assertIn(f"sample001_{role}_login", text)
        scanner = text[text.index("  scanner:"):text.index("  promotion:")]
        self.assertIn("target: /objects/quarantine", scanner)
        self.assertIn("read_only: true", scanner)
        self.assertNotIn('objects:/objects', scanner)

    def test_compose_preserves_local_volume_compatibility_contract(self) -> None:
        text = (SAMPLE / "deploy/compose/compose.yaml").read_text(encoding="utf-8")
        self.assertIn("- postgres-data:/var/lib/postgresql", text)
        self.assertNotIn("- postgres-data:/var/lib/postgresql/data", text)
        objects_init = text[text.index("  objects-init:"):text.index("  api:")]
        self.assertIn("mkdir -p /objects/quarantine /objects/clean", objects_init)
        self.assertNotIn("install -d", objects_init)
        self.assertNotIn("cap_add:", objects_init)

        object_storage_services = ("api", "scanner", "promotion", "deletion", "reconciliation")
        for index, service in enumerate(object_storage_services):
            next_service = object_storage_services[index + 1] if index + 1 < len(object_storage_services) else "frontend"
            section = text[text.index(f"  {service}:"):text.index(f"  {next_service}:")]
            self.assertIn('SAMPLE001_ALLOW_RELAXED_STORAGE_PERMISSIONS: "true"', section)
            self.assertIn('user: "0:0"', section)

        bff = text[text.index("  bff:"):text.index("  scanner:")]
        self.assertNotIn("SAMPLE001_ALLOW_RELAXED_STORAGE_PERMISSIONS", bff)
        self.assertNotIn('user: "0:0"', bff)

    def test_demo_fakes_have_no_production_shaped_image_targets(self) -> None:
        dockerfile = (SAMPLE / "services/Dockerfile").read_text(encoding="utf-8")
        self.assertNotRegex(dockerfile, r"(?m)^FROM (?:fake-)?scanner-demo AS scanner$")
        self.assertNotRegex(dockerfile, r"(?m)^FROM fake-oidc-development AS fake-oidc$")
        chart_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SAMPLE / "deploy/helm/sample-001").rglob("*") if path.is_file()
        )
        self.assertNotIn("fake-eicar", chart_text)
        self.assertNotIn("fake-scanner", chart_text)

    def test_migration_defines_service_capability_roles(self) -> None:
        migration = (SAMPLE / "db/migrations/00001_secure_documents.sql").read_text(encoding="utf-8")
        for role in ("bff", "api", "scanner", "promotion", "deletion"):
            self.assertIn(f"CREATE ROLE sample001_{role} NOLOGIN", migration)

    def test_chart_has_no_forbidden_install_objects(self) -> None:
        chart = SAMPLE / "deploy/helm/sample-001"
        rendered_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (chart / "templates").glob("*.yaml")
        ).lower()
        for forbidden in ("kind: secret", "kind: job", "kind: cronjob", "kind: clusterrole", "kind: customresourcedefinition"):
            self.assertNotIn(forbidden, rendered_sources)
        self.assertNotIn("fake-oidc", rendered_sources)
        self.assertNotIn("postgres", rendered_sources)

    def test_chart_requires_external_secrets_and_digest_images(self) -> None:
        chart = SAMPLE / "deploy/helm/sample-001"
        schema = (chart / "values.schema.json").read_text(encoding="utf-8")
        deployments = (chart / "templates/deployments.yaml").read_text(encoding="utf-8")
        self.assertIn('"^sha256:[a-f0-9]{64}$"', schema)
        self.assertIn("secretRef: {name:", deployments)
        self.assertIn("runAsNonRoot: true", deployments)
        self.assertIn("readOnlyRootFilesystem: true", deployments)

    def test_pipeline_has_no_delivery_capability(self) -> None:
        text = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8").lower()
        self.assertRegex(text, r"stages:\s*\n\s*- validate\s*\n\s*- test\s*\n\s*- build\s*\n\s*- package")
        for forbidden in (
            "stage: deploy", "environment:", "terraform plan", "terraform apply",
            "helm install", "helm upgrade", "kubectl apply", "--push", "cosign sign",
        ):
            self.assertNotIn(forbidden, text)

    def test_external_execution_images_are_digest_pinned(self) -> None:
        pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
        compose = (SAMPLE / "deploy/compose/compose.yaml").read_text(encoding="utf-8")
        references = re.findall(r"(?m)^[ \t]*(?:image|name):[ \t]*([^\s]+)", pipeline)
        references += re.findall(r"(?m)^[ \t]*image:[ \t]*([^\s]+)", compose)
        self.assertTrue(references)
        for reference in references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"@sha256:[a-f0-9]{64}$")
        for dockerfile in (SAMPLE / "apps/frontend/Dockerfile", SAMPLE / "services/Dockerfile"):
            for reference in re.findall(r"(?m)^FROM\s+([^\s]+)", dockerfile.read_text(encoding="utf-8")):
                if reference == "scratch" or ":" not in reference:
                    continue
                with self.subTest(reference=reference):
                    self.assertRegex(reference, r"@sha256:[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
