"""Docker Compose configuration regressions."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class ComposeConfigurationTests(unittest.TestCase):
    project_dir = Path(__file__).parents[1]

    def _render_compose(self, env_text: str) -> dict:
        docker = shutil.which("docker")
        if not docker:
            self.skipTest("Docker CLI is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "compose.env"
            env_path.write_text(env_text, encoding="utf-8")
            result = subprocess.run(
                [
                    docker,
                    "compose",
                    "--env-file",
                    str(env_path),
                    "-f",
                    str(self.project_dir / "docker-compose.yml"),
                    "config",
                    "--format",
                    "json",
                ],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_model_route_environment_is_expanded_from_env_file(self):
        rendered = self._render_compose(
            "\n".join(
                [
                    "LITELLM_PROXY_URL=http://proxy.example.test:4000",
                    "LITELLM_MASTER_KEY=compose-test-master-key",
                    "OLLAMA_BASE_URL=http://ollama.example.test:11434",
                ]
            )
        )
        api_environment = rendered["services"]["api"]["environment"]
        self.assertEqual(
            api_environment["LITELLM_PROXY_URL"],
            "http://proxy.example.test:4000",
        )
        self.assertEqual(
            api_environment["LITELLM_MASTER_KEY"],
            "compose-test-master-key",
        )
        self.assertEqual(
            api_environment["OLLAMA_BASE_URL"],
            "http://ollama.example.test:11434",
        )

    def test_compose_defaults_ollama_to_the_host_gateway(self):
        rendered = self._render_compose("")
        api = rendered["services"]["api"]
        self.assertEqual(
            api["environment"]["OLLAMA_BASE_URL"],
            "http://host.docker.internal:11434",
        )
        self.assertEqual(api["environment"]["LITELLM_MASTER_KEY"], "")
        self.assertIn("host.docker.internal=host-gateway", api["extra_hosts"])

    def test_env_example_does_not_enable_placeholder_cloud_credentials(self):
        values = {}
        for raw_line in (self.project_dir / ".env.example").read_text(
            encoding="utf-8-sig"
        ).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "LONGCAT_API_KEY",
            "LITELLM_MASTER_KEY",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
        ):
            self.assertEqual(values[key], "", key)


if __name__ == "__main__":
    unittest.main()
