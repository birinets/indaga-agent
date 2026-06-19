"""Host integration — register Indaga's MCP server + skills with agent hosts (the Genomi pattern).

Indaga ships NO host-specific plugin code. It is a standard MCP-stdio server (``indaga serve``), and
OpenClaw / Hermes / Claude Code all consume external MCP servers generically — exactly how Genomi
integrates. So "the OpenClaw/Hermes adapter" is just two mechanical steps, both generated here:

  1. an MCP-server entry in each host's config file
     (OpenClaw ``~/.openclaw/openclaw.json`` → ``mcp.servers.indaga``,
      Hermes  ``~/.hermes/config.yaml``    → ``mcp_servers.indaga``,
      Claude  ``~/.claude.json``           → ``mcpServers.indaga``);
  2. symlinking Indaga's ``SKILL.md`` files into the host's ``~/.<host>/skills/`` dir
     (an umbrella ``indaga`` + one ``indaga-<capability>`` per skill).

``plan()`` computes both without touching anything (the dry-run report); ``apply()`` merges the JSON
configs (preserving existing entries), writes the Hermes YAML when absent (else prints the snippet to
add by hand), and creates the skill symlinks. OpenClaw's MCP client (SDK 1.29.0) already reads the
``structuredContent`` / ``outputSchema`` Indaga emits, so no shim is needed. stdlib only.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# host key → (config file, key-path to the MCP-servers dict)
_JSON_HOSTS = {
    "openclaw": ("~/.openclaw/openclaw.json", ["mcp", "servers"]),
    "claude": ("~/.claude.json", ["mcpServers"]),
}
_YAML_HOSTS = {
    "hermes": ("~/.hermes/config.yaml", ["mcp_servers"]),
}
ALL_HOSTS = (*_JSON_HOSTS, *_YAML_HOSTS)


def _skills_root() -> Path:
    env = os.environ.get("INDAGA_SKILLS")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "skills"


def _src_root() -> str:
    # src/indaga/runtime/host_install.py → parents[2] = the src/ dir
    return str(Path(__file__).resolve().parents[2])


def mcp_server_spec(subject_id: str, user_dir: str) -> dict:
    """The ``{command, args[, env]}`` an MCP host spawns to run Indaga's stdio server for this subject.
    Prefers the installed ``indaga`` console script; falls back to ``python -m`` + ``PYTHONPATH``."""
    serve_args = ["serve", "--subject", subject_id, "--user-dir", str(user_dir)]
    exe = shutil.which("indaga")
    if exe:
        return {"command": exe, "args": serve_args}
    return {"command": sys.executable, "args": ["-m", "indaga.interfaces.cli", *serve_args],
            "env": {"PYTHONPATH": _src_root()}}


def _host_skills_dir(host: str) -> Path:
    return Path(f"~/.{host}/skills").expanduser()


def skill_links(host: str) -> list[tuple[Path, Path]]:
    """(symlink, target) pairs: the umbrella ``indaga`` + one ``indaga-<cap>`` per capability skill."""
    skills = _skills_root()
    hdir = _host_skills_dir(host)
    pairs = [(hdir / "indaga", skills)]
    for skill_md in sorted(skills.glob("*/SKILL.md")):
        cap = skill_md.parent.name
        pairs.append((hdir / f"indaga-{cap}", skills / cap))
    return pairs


def _json_snippet(key_path: list[str], spec: dict, *, name: str = "indaga") -> dict:
    node: dict = {name: spec}
    for key in reversed(key_path):
        node = {key: node}
    return node


def _yaml_block(spec: dict, *, name: str = "indaga") -> str:
    """Render the Hermes ``mcp_servers`` block as YAML by hand (stdlib-only; the shape is fixed)."""
    lines = ["mcp_servers:", f"  {name}:", f"    command: {spec['command']}", "    args:"]
    lines += [f"      - {a}" for a in spec["args"]]
    if spec.get("env"):
        lines.append("    env:")
        lines += [f"      {k}: {v}" for k, v in spec["env"].items()]
    return "\n".join(lines) + "\n"


def _merge_json_config(cfg_path: Path, key_path: list[str], spec: dict, *, name: str = "indaga") -> dict:
    """Merge the indaga MCP entry into an existing JSON config WITHOUT clobbering other keys."""
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8")) or {}
        except ValueError:
            data = {}
    node = data
    for key in key_path:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            node[key] = nxt
        node = nxt
    node[name] = spec
    return data


def plan(subject_id: str, user_dir: str, hosts: list[str]) -> dict:
    """Compute (do NOT apply) the integration for each host: the config snippet + the skill links."""
    spec = mcp_server_spec(subject_id, user_dir)
    out: dict = {"mcp_server": spec, "hosts": {}}
    for host in hosts:
        links = [(str(link), str(target)) for link, target in skill_links(host)]
        if host in _JSON_HOSTS:
            cfg, key = _JSON_HOSTS[host]
            out["hosts"][host] = {"config_file": cfg, "format": "json",
                                  "snippet": _json_snippet(key, spec), "skills": links}
        else:
            cfg, _ = _YAML_HOSTS[host]
            out["hosts"][host] = {"config_file": cfg, "format": "yaml",
                                  "snippet": _yaml_block(spec), "skills": links}
    return out


def apply(subject_id: str, user_dir: str, hosts: list[str]) -> dict:
    """Apply: merge JSON configs (preserving existing), write the Hermes YAML when absent, symlink skills."""
    spec = mcp_server_spec(subject_id, user_dir)
    results: dict = {}
    for host in hosts:
        actions: list[str] = []
        if host in _JSON_HOSTS:
            cfg_path = Path(_JSON_HOSTS[host][0]).expanduser()
            merged = _merge_json_config(cfg_path, _JSON_HOSTS[host][1], spec)
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
            actions.append(f"merged indaga MCP server into {cfg_path}")
        else:
            cfg_path = Path(_YAML_HOSTS[host][0]).expanduser()
            if cfg_path.exists():
                actions.append(f"{cfg_path} exists — add this block manually:\n{_yaml_block(spec)}")
            else:
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(_yaml_block(spec), encoding="utf-8")
                actions.append(f"wrote {cfg_path}")
        linked = 0
        for link, target in skill_links(host):
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink() or link.exists():
                link.unlink()
            try:
                link.symlink_to(target)
                linked += 1
            except OSError as exc:
                actions.append(f"skill link failed {link}: {exc}")
        actions.append(f"linked {linked} skills into {_host_skills_dir(host)}")
        results[host] = actions
    return {"mcp_server": spec, "applied": results}


def _verify_tools() -> dict:
    """Post-install smoke check: `indaga tools` must list the base tools."""
    import os
    import subprocess
    import sys
    try:
        r = subprocess.run([sys.executable, "-m", "indaga.interfaces.cli", "tools"],
                           env={**os.environ, "PYTHONPATH": _src_root()},
                           capture_output=True, text=True, timeout=90)
        return {"ok": r.returncode == 0, "returncode": r.returncode}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def install_for_agents(subject_id: str, user_dir: str, hosts: list[str], *, libraries=None,
                       write: bool = False, force: bool = False, verify: bool = True) -> dict:
    """One-shot agent install (the Genomi `install_for_agents.py` flow, in-package): download reference
    libraries → wire the given hosts (MCP config + skill symlinks) → verify. Dry-run by default (no
    downloads, no host writes — just the plan + a missing-libraries report); ``write=True`` performs it.
    Re-uses ``reference.install`` + ``apply``/``plan`` so there is ONE implementation behind both
    ``indaga install-for-agents`` and ``scripts/install_for_agents.py``."""
    report: dict = {}
    if write:
        from ..reference import install as ref_install
        libs = None if (not libraries or list(libraries) == ["everything"]) else list(libraries)
        report["libraries"] = ref_install(libs, force=force)
        report["hosts"] = apply(subject_id, user_dir, hosts)
        if verify:
            report["verify"] = _verify_tools()
    else:
        from ..reference import check_all
        st = check_all()
        report["libraries"] = {"dry_run": True, "installed": st["installed"], "missing": st["missing"]}
        report["hosts"] = {"dry_run": plan(subject_id, user_dir, hosts)}
    return report


def render_report(planned: dict) -> str:
    """A copy-pasteable dry-run report from ``plan()``."""
    lines = ["Indaga host integration (the Genomi pattern — Indaga is a generic MCP server).",
             "", f"MCP server command: {planned['mcp_server']['command']} "
             f"{' '.join(planned['mcp_server']['args'])}", ""]
    for host, h in planned["hosts"].items():
        lines.append(f"== {host} ==")
        lines.append(f"  add to {h['config_file']}:")
        body = json.dumps(h["snippet"], indent=2) if h["format"] == "json" else h["snippet"].rstrip()
        lines += ["    " + ln for ln in body.splitlines()]
        lines.append(f"  symlink {len(h['skills'])} skills into ~/.{host}/skills/ "
                     f"(indaga + indaga-<capability>)")
        lines.append("")
    lines.append("Re-run with --write to merge the configs + create the skill symlinks.")
    return "\n".join(lines)
