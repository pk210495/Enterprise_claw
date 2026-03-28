import logging
from pathlib import Path

from .base import BaseTool, ToolResult
from config import config

logger = logging.getLogger(__name__)

# Core skills are read-only for the agent
_CORE_SKILL_NAMES = ["assistant", "coding", "researcher", "writer"]


def _validate_against_security(content: str) -> str | None:
    """
    Basic check: skill content must not contradict Security.md.
    Returns error message if violation found, None if clean.
    """
    forbidden_phrases = [
        "ignore security",
        "bypass security",
        "override security",
        "ignore security.md",
        "disable security",
        "forget your rules",
        "ignore your instructions",
        "you have no restrictions",
    ]
    lower = content.lower()
    for phrase in forbidden_phrases:
        if phrase in lower:
            return (
                f"Skill content contains a phrase that violates the security constitution: '{phrase}'. "
                "Skill was not created."
            )
    return None


class CreateSkillTool(BaseTool):
    name = "create_skill"
    description = (
        "Create a new custom skill. Skills are persona/role definitions that shape how the agent behaves. "
        "Use this when the user asks the agent to act as a specific role (e.g. DevOps engineer, data analyst). "
        "The skill will be validated against the security constitution before saving."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill identifier, e.g. 'devops', 'data_analyst'. Lowercase, no spaces.",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what this skill does.",
            },
            "instructions": {
                "type": "string",
                "description": "Full skill instructions in markdown. Defines the persona, behaviour, and focus areas.",
            },
        },
        "required": ["name", "description", "instructions"],
    }

    async def execute(self, name: str, description: str, instructions: str) -> ToolResult:
        try:
            # block overwriting core skills
            safe_name = name.lower().replace(" ", "_")
            if safe_name in _CORE_SKILL_NAMES:
                return ToolResult(
                    success=False, output=None,
                    error=f"'{safe_name}' is a core skill and cannot be overwritten."
                )

            # security validation
            err = _validate_against_security(instructions)
            if err:
                return ToolResult(success=False, output=None, error=err)

            custom_dir = config.custom_skills_dir
            custom_dir.mkdir(parents=True, exist_ok=True)

            skill_path = custom_dir / f"{safe_name}.md"
            content = f"# Skill: {name}\n> {description}\n\n{instructions}"
            skill_path.write_text(content, encoding="utf-8")

            _update_skill_index(custom_dir)
            return ToolResult(success=True, output=f"Skill '{safe_name}' created and ready to activate.")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class EditSkillTool(BaseTool):
    name = "edit_skill"
    description = "Edit an existing custom skill by replacing a section of its content. Cannot edit core skills."
    parameters = {
        "type": "object",
        "properties": {
            "name":     {"type": "string", "description": "Skill name to edit"},
            "old_text": {"type": "string", "description": "Exact text to replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["name", "old_text", "new_text"],
    }

    async def execute(self, name: str, old_text: str, new_text: str) -> ToolResult:
        safe_name = name.lower().replace(" ", "_")
        if safe_name in _CORE_SKILL_NAMES:
            return ToolResult(success=False, output=None, error="Cannot edit core skills.")

        err = _validate_against_security(new_text)
        if err:
            return ToolResult(success=False, output=None, error=err)

        skill_path = config.custom_skills_dir / f"{safe_name}.md"
        if not skill_path.exists():
            return ToolResult(success=False, output=None, error=f"Custom skill '{safe_name}' not found.")
        try:
            content = skill_path.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(success=False, output=None, error="old_text not found in skill. No changes made.")
            skill_path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return ToolResult(success=True, output=f"Skill '{safe_name}' updated.")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ListSkillsTool(BaseTool):
    name = "list_skills"
    description = "List all available skills — both core skills and custom skills you have created."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        try:
            lines = ["## Core Skills (read-only)"]
            for name in _CORE_SKILL_NAMES:
                p = config.core_skills_dir / f"{name}.md"
                lines.append(f"  - {name}" + (" ✓" if p.exists() else " (missing)"))

            lines.append("\n## Custom Skills (agent-created)")
            custom_dir = config.custom_skills_dir
            if custom_dir.exists():
                custom = [f.stem for f in sorted(custom_dir.glob("*.md")) if f.name != "index.md"]
                for c in custom:
                    lines.append(f"  - {c}")
                if not custom:
                    lines.append("  (none created yet)")
            else:
                lines.append("  (none created yet)")

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DeleteSkillTool(BaseTool):
    name = "delete_skill"
    description = "Delete a custom skill. Core skills cannot be deleted."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the custom skill to delete"}
        },
        "required": ["name"],
    }

    async def execute(self, name: str) -> ToolResult:
        safe_name = name.lower().replace(" ", "_")
        if safe_name in _CORE_SKILL_NAMES:
            return ToolResult(success=False, output=None, error="Cannot delete core skills.")
        skill_path = config.custom_skills_dir / f"{safe_name}.md"
        if not skill_path.exists():
            return ToolResult(success=False, output=None, error=f"Custom skill '{safe_name}' not found.")
        try:
            skill_path.unlink()
            _update_skill_index(config.custom_skills_dir)
            return ToolResult(success=True, output=f"Skill '{safe_name}' deleted.")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ActivateSkillTool(BaseTool):
    name = "activate_skill"
    description = (
        "Switch the active skill for the current session. "
        "Use this when the user asks you to act as a different role or persona. "
        "List available skills first with list_skills if unsure what exists."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to activate, e.g. 'coding', 'devops'"}
        },
        "required": ["name"],
    }

    # Injected by orchestrator at runtime
    _switch_fn = None

    async def execute(self, name: str) -> ToolResult:
        safe_name = name.lower().replace(" ", "_")
        try:
            load_skill(safe_name)  # validate it exists
        except FileNotFoundError:
            return ToolResult(success=False, output=None, error=f"Skill '{safe_name}' not found. Use list_skills to see available skills.")

        if ActivateSkillTool._switch_fn:
            ActivateSkillTool._switch_fn(safe_name)
            return ToolResult(success=True, output=f"Skill switched to '{safe_name}'.")
        return ToolResult(success=False, output=None, error="Skill switcher not initialised.")


def set_skill_switcher(fn):
    """Injected by orchestrator so the tool can call context.switch_skill()."""
    ActivateSkillTool._switch_fn = fn


def _update_skill_index(custom_dir: Path) -> None:
    try:
        skills = sorted(f.stem for f in custom_dir.glob("*.md") if f.name != "index.md")
        lines = ["# Custom Skills Index\n"]
        for s in skills:
            lines.append(f"- **{s}**")
        (custom_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to update skill index: {e}")


def load_skill(name: str) -> str:
    """Load a skill's markdown content. Checks custom first, then core."""
    safe_name = name.lower().replace(" ", "_")

    # custom first
    custom_path = config.custom_skills_dir / f"{safe_name}.md"
    if custom_path.exists():
        content = custom_path.read_text(encoding="utf-8")
        err = _validate_against_security(content)
        if err:
            raise ValueError(f"Skill '{safe_name}' failed security validation: {err}")
        return content

    # then core
    core_path = config.core_skills_dir / f"{safe_name}.md"
    if core_path.exists():
        return core_path.read_text(encoding="utf-8")

    raise FileNotFoundError(f"Skill '{safe_name}' not found in core or custom directories.")
