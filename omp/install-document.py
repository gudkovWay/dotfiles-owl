#!/usr/bin/env python3
"""Install only the document extension and its Noctalia theme template."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

TOKEN = re.compile(r"\{\{ colors\.([a-z_]+)\.default\.hex \}\}")
HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
SECTION = "omp_document_colors"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(source: Path, palette_path: Path, dry_run: bool = False) -> None:
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    agent = Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".omp/agent"))
    template = config / "noctalia/templates/omp-nibelung-dark.json"
    registration = config / "noctalia/templates.toml"
    theme_path = agent / "themes/nibelung-dark.json"
    extension = agent / "extensions/document-markdown"
    extension_source = source / "omp/extensions/document-markdown"
    template_source = source / "omp/noctalia/nibelung-dark.json"
    if not extension_source.is_dir() or not template_source.is_file():
        raise ValueError("Document Markdown sources are missing")
    if extension.exists() and not extension.is_symlink():
        raise ValueError(f"Refusing to replace a real extension directory: {extension}")
    if registration.is_symlink() or theme_path.is_symlink() or template.is_symlink():
        raise ValueError("Refusing to replace symlinked theme/template files; resolve ownership first")
    old_registration = registration.read_text() if registration.exists() else ""
    parsed = tomllib.loads(old_registration)
    entry = {
        "input_path": str(template),
        "output_path": str(theme_path),
    }
    existing = parsed.get("theme", {}).get("templates", {}).get("user", {}).get(SECTION)
    if existing is not None and existing != entry:
        raise ValueError(f"Noctalia template {SECTION} already has a different owner/configuration")
    new_registration = old_registration
    if existing is None:
        new_registration = old_registration.rstrip() + f"\n\n[theme.templates.user.{SECTION}]\n"
        new_registration += "\n".join(f"{key} = {json.dumps(value)}" for key, value in entry.items()) + "\n"
    tomllib.loads(new_registration)
    if dry_run:
        print(f"install document extension: {extension}")
        print(f"register Noctalia template: {template} -> {theme_path}")
        return
    palette = json.loads(palette_path.read_text())
    # The cached Noctalia export includes both modes. Seed the selected current
    # dark theme; future mode/wallpaper changes are rendered by Noctalia itself.
    tokens = palette.get("dark", palette)
    template_text = template_source.read_text()

    def replace(match: re.Match[str]) -> str:
        color = tokens.get(match[1])
        if not isinstance(color, str) or not HEX.fullmatch(color):
            raise ValueError(f"Palette is missing a valid {match[1]} color")
        return color

    theme_text = TOKEN.sub(replace, template_text)
    generated = json.loads(theme_text)
    if generated.get("name") != "nibelung-dark" or "{{" in theme_text:
        raise ValueError("Invalid generated OMP theme")
    # Validate every variable before making any live mutation.
    for color in generated["vars"].values():
        if not HEX.fullmatch(color):
            raise ValueError("Generated OMP theme contains an invalid color")
    changes = [(registration, new_registration), (template, template_text), (theme_path, theme_text)]
    changes = [(path, content) for path, content in changes if not path.exists() or path.read_text() != content]
    if changes:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = state / "omp-document-markdown/backups" / stamp
        for path, _ in changes:
            if path.exists():
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup / path.name)
        # Install the complete template/output before exposing registration.
        for path, content in reversed(changes):
            atomic_write(path, content)
        print(f"Theme/template backup: {backup}" if backup.exists() else "Installed new theme/template files")
    extension.parent.mkdir(parents=True, exist_ok=True)
    if not extension.is_symlink() or extension.resolve() != extension_source.resolve():
        temporary_link = extension.parent / f".document-markdown.{os.getpid()}"
        try:
            temporary_link.symlink_to(extension_source.resolve(), target_is_directory=True)
            os.replace(temporary_link, extension)
        finally:
            temporary_link.unlink(missing_ok=True)
    print(f"Document extension: {extension} -> {extension_source.resolve()}")
    print(f"Noctalia sync: {template} -> {theme_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--palette", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    palette = args.palette or cache / "noctalia/stylus-sync/palette.json"
    install(Path(__file__).resolve().parents[1], palette, args.dry_run)


if __name__ == "__main__":
    main()
