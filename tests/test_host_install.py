"""P2 — host integration (the Genomi pattern): MCP-server config snippets + skill symlinks."""

import json

import pytest

from indaga.interfaces import host_install


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("# indaga root skill")
    for cap in ("genome", "labs"):
        (skills / cap).mkdir()
        (skills / cap / "SKILL.md").write_text(f"# {cap}")
    monkeypatch.setenv("INDAGA_SKILLS", str(skills))
    return home, skills


def test_mcp_server_spec_has_serve_args(env):
    spec = host_install.mcp_server_spec("demo", "/u/demo")
    assert spec["command"]
    assert "serve" in spec["args"]
    assert "demo" in spec["args"] and "/u/demo" in spec["args"]


def test_openclaw_snippet_shape(env):
    plan = host_install.plan("demo", "/u/demo", ["openclaw"])
    snippet = plan["hosts"]["openclaw"]["snippet"]
    assert "serve" in snippet["mcp"]["servers"]["indaga"]["args"]
    assert plan["hosts"]["openclaw"]["config_file"] == "~/.openclaw/openclaw.json"


def test_claude_snippet_shape(env):
    plan = host_install.plan("demo", "/u/demo", ["claude"])
    assert "indaga" in plan["hosts"]["claude"]["snippet"]["mcpServers"]


def test_hermes_yaml_snippet(env):
    snippet = host_install.plan("demo", "/u/demo", ["hermes"])["hosts"]["hermes"]["snippet"]
    assert "mcp_servers:" in snippet and "indaga:" in snippet and "serve" in snippet


def test_skill_links_include_umbrella_and_caps(env):
    links = {link.name: target for link, target in host_install.skill_links("openclaw")}
    assert "indaga" in links
    assert "indaga-genome" in links and "indaga-labs" in links
    assert links["indaga-genome"].name == "genome"


def test_apply_merges_json_preserving_existing(env):
    home, _ = env
    cfg = home / ".openclaw" / "openclaw.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcp": {"servers": {"other": {"command": "x"}}}, "theme": "dark"}))
    host_install.apply("demo", "/u/demo", ["openclaw"])
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark"                          # unrelated key preserved
    assert "other" in data["mcp"]["servers"]                # existing server preserved
    assert "serve" in data["mcp"]["servers"]["indaga"]["args"]


def test_apply_creates_skill_symlinks(env):
    home, skills = env
    host_install.apply("demo", "/u/demo", ["openclaw"])
    umbrella = home / ".openclaw" / "skills" / "indaga"
    assert umbrella.is_symlink() and umbrella.resolve() == skills.resolve()
    assert (home / ".openclaw" / "skills" / "indaga-genome").is_symlink()


def test_apply_writes_fresh_hermes_yaml(env):
    home, _ = env
    host_install.apply("demo", "/u/demo", ["hermes"])
    cfg = home / ".hermes" / "config.yaml"
    assert cfg.exists()
    assert "mcp_servers:" in cfg.read_text() and "indaga:" in cfg.read_text()


def test_install_for_agents_dry_run(env, monkeypatch):
    # dry-run: no downloads, no host writes — just a libraries status + the host plan
    monkeypatch.setenv("INDAGA_HOME", str(env[0] / ".indaga"))
    rep = host_install.install_for_agents("demo", "/u/demo", ["openclaw"], write=False, verify=False)
    assert rep["libraries"]["dry_run"] is True
    assert "missing" in rep["libraries"]
    assert "openclaw" in rep["hosts"]["dry_run"]["hosts"]
    assert not (env[0] / ".openclaw" / "openclaw.json").exists()  # nothing written


def test_install_for_agents_write_orchestrates(env, monkeypatch):
    home, _ = env
    import indaga.reference as ref
    monkeypatch.setattr(ref, "install",
                        lambda libs=None, force=False: {"ok": True, "results": [{"id": "clinvar-grch38", "ok": True}]})
    rep = host_install.install_for_agents("demo", "/u/demo", ["openclaw"], write=True, verify=False)
    assert rep["libraries"]["ok"] is True            # downloads ran (mocked)
    assert "applied" in rep["hosts"]                 # host wired
    assert (home / ".openclaw" / "openclaw.json").exists()
    assert (home / ".openclaw" / "skills" / "indaga").is_symlink()
