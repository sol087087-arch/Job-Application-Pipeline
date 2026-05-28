from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelTaskConfig:
    name: str
    primary: str
    fallback: str | None
    prompt: Path
    temperature: float
    must_differ_from_task: str | None = None


@dataclass(frozen=True)
class ModelPolicy:
    provider: str
    tasks: dict[str, ModelTaskConfig]
    policies: dict[str, Any]

    def task(self, name: str) -> ModelTaskConfig:
        try:
            return self.tasks[name]
        except KeyError as exc:
            raise KeyError(f"Unknown model task: {name}") from exc

    def validate(self) -> None:
        if self.policies.get("require_independent_resume_quality_audit", False):
            tailoring = self.task("tailoring")
            audit = self.task("resume_quality_audit")
            if audit.primary == tailoring.primary:
                raise ValueError(
                    "resume_quality_audit.primary must differ from tailoring.primary for independent review"
                )
            if audit.must_differ_from_task and audit.must_differ_from_task != "tailoring":
                raise ValueError("resume_quality_audit.must_differ_from_task must be 'tailoring'")


class ModelPolicyLoader:
    def __init__(self, default_path: str | Path = "config/models.json") -> None:
        self.default_path = Path(default_path)

    def load(self, path: str | Path | None = None) -> ModelPolicy:
        policy_path = Path(path) if path is not None else self.default_path
        if path is None and not policy_path.exists():
            json_fallback = policy_path.with_suffix(".json")
            if json_fallback.exists():
                policy_path = json_fallback
        raw = policy_path.read_text(encoding="utf-8-sig")
        data = self._loads(raw, policy_path)
        if not isinstance(data, dict):
            raise ValueError(f"Model policy root must be a mapping: {policy_path}")
        models = data.get("models")
        if not isinstance(models, dict):
            raise ValueError("Model policy missing models mapping")

        tasks: dict[str, ModelTaskConfig] = {}
        for name, value in models.items():
            if not isinstance(value, dict):
                raise ValueError(f"Model task must be a mapping: {name}")
            tasks[name] = ModelTaskConfig(
                name=name,
                primary=str(value["primary"]),
                fallback=str(value["fallback"]) if value.get("fallback") else None,
                prompt=Path(str(value["prompt"])),
                temperature=float(value.get("temperature", 0.0)),
                must_differ_from_task=(
                    str(value["must_differ_from_task"]) if value.get("must_differ_from_task") else None
                ),
            )

        policy = ModelPolicy(
            provider=str(data.get("provider", "openrouter")),
            tasks=tasks,
            policies=dict(data.get("policies") or {}),
        )
        policy.validate()
        return policy

    def _loads(self, raw: str, path: Path) -> Any:
        if path.suffix.lower() == ".json":
            return json.loads(raw)
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("YAML model policy loading requires PyYAML. Use JSON or install dependencies.") from exc
        return yaml.safe_load(raw)
