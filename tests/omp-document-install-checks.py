#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("document_installer", root / "omp/install-document.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="omp-document-install-") as temporary:
    home = Path(temporary)
    os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"), XDG_STATE_HOME=str(home / "state"))
    os.environ["PI_CODING_AGENT_DIR"] = str(home / "agent")
    config = home / "config/noctalia"
    config.mkdir(parents=True)
    registration = config / "templates.toml"
    previous = '[theme.templates.user.tmux_colors]\ninput_path="keep-in"\noutput_path="keep-out"\n'
    registration.write_text(previous)
    theme_path = home / "agent/themes/nibelung-dark.json"
    theme_path.parent.mkdir(parents=True)
    theme_path.write_text('{"owner":"original-theme"}')
    roles = ["primary", "secondary", "tertiary", "surface", "surface_container", "surface_container_low", "surface_container_high", "surface_container_highest", "on_surface", "on_surface_variant", "outline", "outline_variant", "error"]
    palette = home / "palette.json"
    palette.write_text(json.dumps({"dark": {role: f"#{index + 1:06x}" for index, role in enumerate(roles)}}))
    module.install(root, palette)
    assert registration.read_text().startswith(previous.rstrip())
    table = tomllib.loads(registration.read_text())["theme"]["templates"]["user"]
    assert table["tmux_colors"]["input_path"] == "keep-in"
    assert table[module.SECTION]["output_path"] == str(theme_path)
    generated = json.loads(theme_path.read_text())
    assert generated["name"] == "nibelung-dark"
    assert generated["vars"]["fg"] == json.loads(palette.read_text())["dark"]["on_surface"]
    assert generated["vars"]["level0"] != generated["vars"]["custom-message-bg"]
    assert (home / "agent/extensions/document-markdown").resolve() == root / "omp/extensions/document-markdown"
    assert list((home / "state/omp-document-markdown/backups").glob("*/nibelung-dark.json"))[0].read_text() == '{"owner":"original-theme"}'
    print("OK: isolated deployment preserves other templates, theme identity and backups")
    before = (registration.read_bytes(), theme_path.read_bytes(), theme_path.stat().st_mtime_ns)
    module.install(root, palette)
    assert before == (registration.read_bytes(), theme_path.read_bytes(), theme_path.stat().st_mtime_ns)
    assert registration.read_text().count(f"[theme.templates.user.{module.SECTION}]") == 1
    print("OK: repeated deployment is idempotent")
    palette.write_text('{"dark":{"primary":"broken"}}')
    try:
        module.install(root, palette)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid palette was accepted")
    assert before == (registration.read_bytes(), theme_path.read_bytes(), theme_path.stat().st_mtime_ns)
    print("OK: invalid palette cannot partially overwrite theme/registration")
    # A real extension directory is user-owned; deployment must refuse it.
    extension = home / "agent/extensions/document-markdown"
    extension.unlink()
    extension.mkdir()
    (extension / "owner").write_text("keep")
    try:
        module.install(root, palette)
    except ValueError:
        pass
    else:
        raise AssertionError("real extension directory was replaced")
    assert (extension / "owner").read_text() == "keep"
    print("OK: real extension directories are not replaced")
print("PASS: 4 document-install checks")
