from pathlib import Path
from config import config


def list_all_skills() -> dict[str, str]:
    """Return dict of {skill_name: source} for all available skills."""
    skills = {}
    for f in sorted(config.core_skills_dir.glob("*.md")):
        skills[f.stem] = "core"
    if config.custom_skills_dir.exists():
        for f in sorted(config.custom_skills_dir.glob("*.md")):
            if f.name != "index.md":
                skills[f.stem] = "custom"
    return skills
