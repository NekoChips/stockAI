import unittest
from pathlib import Path


class DeploymentAssetTests(unittest.TestCase):
    def test_image_compose_pulls_registry_image_without_local_build(self):
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("ghcr.io/nekochips/stockai", compose)
        self.assertIn("image: ghcr.io/nekochips/stockai:latest", compose)
        self.assertIn("pull_policy: always", compose)
        self.assertIn("healthcheck:", compose)
        self.assertIn("http://127.0.0.1:8765/readyz", compose)
        self.assertNotIn("http://127.0.0.1:8765/api/dashboard', timeout=5", compose)
        self.assertNotIn("build:", compose)

    def test_github_workflow_publishes_latest_and_version_tags(self):
        workflow = Path(".github/workflows/publish-image.yml").read_text(encoding="utf-8")

        self.assertIn("packages: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("docker/build-push-action", workflow)
        self.assertIn("actions/attest@v4", workflow)
        self.assertIn("ghcr.io/nekochips/stockai", workflow)
        self.assertIn("refs/heads/release", workflow)
        self.assertIn("type=ref,event=branch", workflow)
        self.assertIn("type=ref,event=tag", workflow)
        self.assertIn("type=raw,value=latest", workflow)
        self.assertNotIn("value=stable", workflow)

    def test_release_environment_exposes_image_selection(self):
        environment = Path("docker/.env.release.example").read_text(encoding="utf-8")

        self.assertIn("STOCK_AI_IMAGE=ghcr.io/nekochips/stockai", environment)
        self.assertIn("STOCK_AI_IMAGE_TAG=latest", environment)

    def test_nas_compose_can_be_pasted_without_external_files(self):
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("image: ghcr.io/nekochips/stockai:latest", compose)
        self.assertIn('STOCK_AI_MYSQL_HOST: "CHANGE_ME"', compose)
        self.assertIn('STOCK_AI_MYSQL_PASSWORD: "CHANGE_ME"', compose)
        self.assertIn('ALPHAFEED_API_KEY: "CHANGE_ME"', compose)
        self.assertNotIn("./reports:/app/reports", compose)
        self.assertIn("pull_policy: always", compose)
        self.assertNotIn("bootstrap:", compose)
        self.assertNotIn("condition: service_completed_successfully", compose)
        self.assertIn('command: ["monitor", "--config", "config/release.container.yaml"]', compose)
        self.assertNotIn("env_file:", compose)
        self.assertNotIn("build:", compose)
        self.assertNotIn("${", compose)

    def test_release_archive_disables_macos_extended_attributes(self):
        script = Path("scripts/package-release.sh").read_text(encoding="utf-8")

        self.assertIn("COPYFILE_DISABLE=1", script)
        self.assertIn('xattr -cr "$PACKAGE_DIR"', script)
        self.assertIn("tar --no-xattrs", script)
        self.assertIn('"$ROOT/docker-compose.yml"', script)
        self.assertNotIn("docker-compose.nas.yml", script)
        self.assertNotIn("docker-compose.deploy.yml", script)


if __name__ == "__main__":
    unittest.main()
