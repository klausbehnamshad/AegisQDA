"""Read-only local readiness report."""

from __future__ import annotations

from typing import Any

from .config import ROOT, load_config, load_policy
from .languages import model_status
from .local_boundary import (
    ollama_models,
    locked_dependency_drift,
    package_versions,
    reject_proxy_environment,
    validate_loopback_url,
    verify_upstream,
)


def doctor_report() -> tuple[dict[str, Any], bool]:
    report: dict[str, Any] = {"gate": "BLOCKED", "checks": {}, "problems": [], "warnings": []}
    problems: list[str] = report["problems"]
    warnings: list[str] = report["warnings"]
    try:
        config = load_config()
        policy = load_policy(config)
        report["checks"]["config"] = "PASS"
        report["policy_id"] = policy.policy_id
    except Exception:
        report["checks"]["config"] = "FAIL"
        problems.append("configuration or policy validation failed")
        return report, False
    versions = package_versions()
    report["packages"] = versions
    if "MISSING" in versions.values():
        problems.append("one or more required Python packages are missing")
    try:
        drift = locked_dependency_drift(ROOT / "requirements.lock")
        report["dependency_lock_drift"] = drift
        report["checks"]["dependency_lock"] = "PASS" if not drift else "FAIL"
        if drift:
            problems.append("installed Python environment differs from requirements.lock")
    except Exception:
        report["checks"]["dependency_lock"] = "FAIL"
        problems.append("dependency lock validation failed")
    try:
        reject_proxy_environment()
        report["checks"]["proxy_environment"] = "PASS"
    except Exception as exc:
        report["checks"]["proxy_environment"] = "FAIL"
        problems.append(str(exc))
    try:
        base_url = validate_loopback_url(config.execution.ollama_base_url)
        report["checks"]["ollama_endpoint"] = "PASS"
    except Exception:
        report["checks"]["ollama_endpoint"] = "FAIL"
        problems.append("configured Ollama endpoint is not loopback-only")
        base_url = config.execution.ollama_base_url
    languages = model_status()
    report["languages"] = languages
    for code in config.languages.required:
        status = languages[code]
        if not status["release_ready"] or not status["nlp_engine_installed"]:
            problems.append(f"configured local NLP engine is missing for {code}")
    for code in config.languages.optional:
        status = languages[code]
        if not status["release_ready"]:
            warnings.append(f"optional language {code} is blocked: {status['reason']}")
    try:
        models = ollama_models(base_url)
        report["installed_approved_models"] = {
            tag: digest
            for tag, digest in models.items()
            if tag in config.models.dpo_approved_local_allowlist
        }
        report["approved_model_tags"] = config.models.dpo_approved_local_allowlist
        if config.models.default not in models:
            problems.append(
                f"default model {config.models.default} is not installed; "
                "explicit authorization is required before pulling it"
            )
        report["checks"]["ollama"] = "PASS" if config.models.default in models else "FAIL"
    except Exception:
        report["checks"]["ollama"] = "FAIL"
        problems.append("local Ollama model inventory is unavailable")
    try:
        report["upstream_sha256"] = verify_upstream(config)
        report["checks"]["pinned_digqda"] = "PASS"
    except Exception:
        report["checks"]["pinned_digqda"] = "FAIL"
        problems.append("pinned DigQDA snapshot verification failed")
    ready = not problems
    report["gate"] = "READY" if ready else "BLOCKED"
    return report, ready
