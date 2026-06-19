#!/usr/bin/env python3
"""Install Indaga for agent hosts — the one-command source-checkout installer.

Mirrors Genomi's ``scripts/install_for_agents.py``: ties the whole agent-install flow into one entry
point — (optional) editable package install → download reference libraries → wire the chosen hosts
(MCP-server config + skill symlinks) → verify. It is a THIN wrapper: the real flow lives in the package
(``indaga.runtime.host_install.install_for_agents``), which is the same code behind
``indaga install-for-agents`` — one implementation, not two.

Dry-run by default (no downloads, no host writes); ``--write`` performs the install.

    python3 scripts/install_for_agents.py --subject <you> --user-dir /ABS/users/<you>          # preview
    python3 scripts/install_for_agents.py --subject <you> --user-dir /ABS/users/<you> --write   # install
    python3 scripts/install_for_agents.py --subject <you> --user-dir /ABS/users/<you> --write \
            --host openclaw --editable --libraries everything
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# make the package importable from a source checkout (src/ layout) without an install.
_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="install_for_agents",
                                description="Install Indaga for agent hosts (OpenClaw/Hermes/Claude).")
    p.add_argument("--subject", required=True)
    p.add_argument("--user-dir", required=True)
    p.add_argument("--host", default="all", choices=["all", "openclaw", "hermes", "claude"])
    p.add_argument("--libraries", nargs="*", help="reference library ids; empty/'everything' = phase-A core")
    p.add_argument("--editable", action="store_true", help="also run `pip install -e .` first")
    p.add_argument("--write", action="store_true", help="perform it (download + wire); default is a dry-run")
    p.add_argument("--force", action="store_true", help="re-download already-installed libraries")
    p.add_argument("--skip-verify", action="store_true")
    args = p.parse_args(argv)

    if args.editable:
        print("==> pip install -e .")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(_REPO)], check=False)

    from indaga.interfaces import host_install

    hosts = list(host_install.ALL_HOSTS) if args.host == "all" else [args.host]
    mode = "WRITE" if args.write else "dry-run"
    print(f"==> Indaga install-for-agents ({mode}) — hosts: {', '.join(hosts)}")
    rep = host_install.install_for_agents(
        args.subject, args.user_dir, hosts,
        libraries=args.libraries or None, write=args.write, force=args.force, verify=not args.skip_verify)

    libs = rep["libraries"]
    if args.write:
        print(f"  libraries: {'ok' if libs['ok'] else 'SOME FAILED'} ({len(libs['results'])} checked)")
        for host, actions in rep["hosts"]["applied"].items():
            print(f"  [{host}] " + "; ".join(a.splitlines()[0] for a in actions))
        if "verify" in rep:
            print(f"  verify (indaga tools): {'ok' if rep['verify']['ok'] else 'FAILED'}")
        print("\nDone. Next: reload your host's MCP server; Indaga is available via its base tools + host skill.")
    else:
        print(f"  libraries: {len(libs['installed'])} installed, {len(libs['missing'])} missing")
        print(host_install.render_report(rep["hosts"]["dry_run"]))
        print("Re-run with --write to download references + wire the hosts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
