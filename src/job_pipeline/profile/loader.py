from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidateProfile:
    path: Path
    data: dict[str, Any]
    sha256: str

    def require(self, dotted_path: str) -> Any:
        value: Any = self.data
        for part in dotted_path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise KeyError(f"Missing profile field: {dotted_path}")
            value = value[part]
        if value is None:
            raise ValueError(f"Profile field is null: {dotted_path}")
        return value

    def get(self, dotted_path: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_path.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


class ProfileLoader:
    def __init__(self, default_path: str | Path = "private/master_profile.yaml") -> None:
        self.default_path = Path(default_path)

    def load(self, path: str | Path | None = None) -> CandidateProfile:
        profile_path = Path(path) if path is not None else self.default_path
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Profile not found: {profile_path}. Copy config/profile/master_profile.example.yaml "
                "to private/master_profile.yaml and fill it locally."
            )
        raw = profile_path.read_text(encoding="utf-8-sig")
        data = self._loads(raw, profile_path)
        if not isinstance(data, dict):
            raise ValueError(f"Profile root must be a mapping: {profile_path}")
        return CandidateProfile(
            path=profile_path,
            data=data,
            sha256=sha256(raw.encode("utf-8")).hexdigest(),
        )

    def _loads(self, raw: str, path: Path) -> Any:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return json.loads(raw)
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "YAML profile loading requires PyYAML. Install project dependencies or use a JSON profile."
                ) from exc
            return yaml.safe_load(raw)
        raise ValueError(f"Unsupported profile format: {path.suffix}. Use .yaml, .yml, or .json.")
