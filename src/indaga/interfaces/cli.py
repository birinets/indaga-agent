"""Indaga CLI — serve / tools / call / selftest (mirrors genomi/interfaces/cli.py).

Run the MCP server (stdio):
    python3 -m indaga.interfaces.cli serve --subject <subject> --user-dir users/<subject>

Drive the full surface without an MCP client:
    python3 -m indaga.interfaces.cli selftest --subject <subject> --user-dir users/<subject>
"""

from __future__ import annotations

import argparse
import json

from ..operations import base_operations, bootstrap, call_operation
from ..store import Surface
from .mcp import IndagaMCPServer, build_context, serve_stdio


def _cmd_serve(args) -> int:
    ctx = build_context(args.subject, args.user_dir, hr_limit=args.hr_limit,
                        surface=Surface(args.surface), rebuild=args.rebuild)
    serve_stdio(ctx)
    return 0


def _cmd_tools(args) -> int:
    bootstrap.load_all()
    print(json.dumps([op.tool_definition() for op in base_operations()], indent=2))
    return 0


def _cmd_call(args) -> int:
    ctx = build_context(args.subject, args.user_dir, hr_limit=args.hr_limit, surface=Surface(args.surface))
    params = json.loads(args.params) if args.params else {}
    print(json.dumps(call_operation(args.name, params, ctx), indent=2, ensure_ascii=False))
    return 0


def _cmd_impute(args) -> int:
    """Extend a chip to a GRCh38 imputed genome on-device (Beagle + 1000G-30x panel)."""
    import glob
    from ..connectors.impute import impute_genome
    chip = args.chip
    if not chip:
        hits = sorted(glob.glob(f"{args.user_dir}/dna/raw/*.csv") + glob.glob(f"{args.user_dir}/dna/raw/*.txt"))
        chip = hits[0] if hits else None
    if not chip:
        print(json.dumps({"status": "failed", "reason": "no chip file found"}))
        return 1
    chroms = args.chroms.split(",") if args.chroms else None
    rep = impute_genome(args.subject, chip, chroms=chroms, threads=args.threads,
                        mem_gb=args.mem, dr2_min=args.dr2)
    print(json.dumps(rep, indent=2))
    return 0 if rep.get("status") == "imputed" else 1


def _cmd_annotate(args) -> int:
    """Full genome annotation (P/LP screen + polygenic scores) — the one-time heavy step."""
    from ..connectors.annotate import annotate_genome
    # --rebuild re-ingests too, so the AGI is rebuilt from a newly-imputed genome.
    ctx = build_context(args.subject, args.user_dir, surface=Surface(args.surface), rebuild=args.rebuild)
    rep = annotate_genome(ctx.store, args.subject, args.user_dir,
                          run_pgs=not args.no_pgs, rebuild=args.rebuild)
    print(json.dumps(rep, indent=2))
    return 0


def _cmd_pharmcat(args) -> int:
    """Run in-house PharmCAT (PGx) on the subject's imputed genome → own phenotype.json."""
    from ..connectors.pharmcat import run_pharmcat
    rep = run_pharmcat(args.subject)
    print(json.dumps(rep, indent=2))
    return 0 if rep.get("status") == "ok" else 1


def _cmd_ancestry(args) -> int:
    """Estimate continental ancestry (builds the AIM reference on first use)."""
    from ..connectors.ancestry import estimate_ancestry
    rep = estimate_ancestry(args.subject, build_if_missing=True)
    print(json.dumps(rep, indent=2))
    return 0 if rep.get("status") == "ok" else 1


def _cmd_install(args) -> int:
    from ..reference import check_all, install
    if args.check:
        print(json.dumps(check_all(), indent=2))
        return 0
    rep = install(args.libraries or None, force=args.force)
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 1


def _cmd_install_host(args) -> int:
    """Register Indaga's MCP server + skills with an agent host (OpenClaw/Hermes/Claude), the Genomi
    way: a config entry per host + skill symlinks. Dry-run by default; --write applies."""
    from . import host_install
    hosts = list(host_install.ALL_HOSTS) if args.host == "all" else [args.host]
    if args.write:
        print(json.dumps(host_install.apply(args.subject, args.user_dir, hosts), indent=2))
    else:
        print(host_install.render_report(host_install.plan(args.subject, args.user_dir, hosts)))
    return 0


def _cmd_install_for_agents(args) -> int:
    """One-shot agent install (Genomi-style): download references → wire hosts → verify. Dry-run by
    default; --write performs it. Same flow as scripts/install_for_agents.py."""
    from . import host_install
    hosts = list(host_install.ALL_HOSTS) if args.host == "all" else [args.host]
    rep = host_install.install_for_agents(args.subject, args.user_dir, hosts,
                                          libraries=args.libraries or None, write=args.write,
                                          force=args.force, verify=not args.skip_verify)
    libs = rep["libraries"]
    if args.write:
        print(f"libraries: {'ok' if libs['ok'] else 'SOME FAILED'} ({len(libs['results'])} checked)")
        for host, actions in rep["hosts"]["applied"].items():
            print(f"  [{host}] " + "; ".join(a.splitlines()[0] for a in actions))
        if "verify" in rep:
            print(f"verify (indaga tools): {'ok' if rep['verify']['ok'] else 'FAILED'}")
    else:
        print(f"libraries (dry-run): {len(libs['installed'])} installed, {len(libs['missing'])} missing")
        print(host_install.render_report(rep["hosts"]["dry_run"]))
    return 0


def _cmd_selftest(args) -> int:
    ctx = build_context(args.subject, args.user_dir, hr_limit=args.hr_limit,
                        surface=Surface(args.surface), rebuild=args.rebuild)
    srv = IndagaMCPServer(ctx)

    def call(method, params=None, rid=1):
        return srv.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})

    def tool(name, arguments=None):
        r = call("tools/call", {"name": name, "arguments": arguments or {}})
        return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]

    print("initialize ->", call("initialize")["result"]["serverInfo"])
    tl = call("tools/list")
    print("tools/list ->", [t["name"] for t in tl["result"]["tools"]])

    out, _ = tool("clock.state")
    e = out["evidence_envelope"]
    print(f"\nclock.state: state={out.get('state')} nights={out.get('valid_nights')} "
          f"finding={e['finding_state']} readiness={e['answer_readiness']} "
          f"midnight={out.get('biological_midnight')} neg_inf={e['negative_inference']['allowed']}")

    inv, _ = tool("indaga.invoke", {"tool": "clock.biological_midnight", "params": {}})
    print(f"invoke(clock.biological_midnight): dispatched_tool={inv.get('dispatched_tool')} "
          f"midnight={inv.get('biological_midnight')}")

    ctxd, _ = tool("indaga.describe_context")
    print(f"describe_context: sources={ctxd.get('sources')} facts={ctxd.get('fact_count')} "
          f"capabilities={ctxd.get('capabilities')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="indaga")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--subject", required=True)
        sp.add_argument("--user-dir", required=True)
        sp.add_argument("--surface", default="app", choices=["app", "byo_ai", "harness"])
        sp.add_argument("--hr-limit", type=int, default=20000)

    s = sub.add_parser("serve", help="run the MCP server over stdio")
    common(s)
    s.add_argument("--rebuild", action="store_true", help="re-ingest + recompute even if the index exists")
    s.set_defaults(fn=_cmd_serve)

    t = sub.add_parser("tools", help="print the base tool list (JSON)")
    t.set_defaults(fn=_cmd_tools)

    c = sub.add_parser("call", help="call one operation by name")
    common(c)
    c.add_argument("name")
    c.add_argument("--params", help="JSON params object")
    c.set_defaults(fn=_cmd_call)

    st = sub.add_parser("selftest", help="drive the full surface without an MCP client")
    common(st)
    st.add_argument("--rebuild", action="store_true")
    st.set_defaults(fn=_cmd_selftest)

    ins = sub.add_parser("install", help="download reference libraries into ~/.indaga (or --check status)")
    ins.add_argument("libraries", nargs="*", help="library ids; empty = phase-A core")
    ins.add_argument("--check", action="store_true", help="report install status, download nothing")
    ins.add_argument("--force", action="store_true", help="re-fetch already-installed libraries")
    ins.set_defaults(fn=_cmd_install)

    an = sub.add_parser("annotate", help="full genome annotation (P/LP screen + polygenic scores)")
    common(an)
    an.add_argument("--no-pgs", action="store_true", help="screen only, skip polygenic scores")
    an.add_argument("--rebuild", action="store_true", help="recompute even if cached")
    an.set_defaults(fn=_cmd_annotate)

    im = sub.add_parser("impute", help="extend a chip to a GRCh38 imputed genome (Beagle + 1000G-30x)")
    im.add_argument("--subject", required=True)
    im.add_argument("--user-dir", required=True, help="dir holding dna/raw/<chip> (or pass --chip)")
    im.add_argument("--chip", help="explicit chip CSV/TXT path")
    im.add_argument("--chroms", help="comma-separated, e.g. '22' or '1,2,3' (default: all autosomes)")
    im.add_argument("--threads", type=int, default=4)
    im.add_argument("--mem", type=int, default=8, help="Beagle Java heap in GB (big chromosomes need ~24)")
    im.add_argument("--dr2", type=float, default=0.0, help="filter out imputed variants below this DR2")
    im.set_defaults(fn=_cmd_impute)

    pc = sub.add_parser("pharmcat", help="run in-house PharmCAT (PGx) on the imputed genome")
    pc.add_argument("--subject", required=True)
    pc.add_argument("--user-dir", required=False, default="", help="unused; kept for job-runner parity")
    pc.set_defaults(fn=_cmd_pharmcat)

    anc = sub.add_parser("ancestry", help="estimate continental ancestry (builds AIM reference on first use)")
    anc.add_argument("--subject", required=True)
    anc.add_argument("--user-dir", required=False, default="", help="unused; kept for job-runner parity")
    anc.set_defaults(fn=_cmd_ancestry)

    ih = sub.add_parser("install-host",
                        help="register Indaga's MCP server + skills with an agent host (OpenClaw/Hermes/Claude)")
    ih.add_argument("--subject", required=True)
    ih.add_argument("--user-dir", required=True)
    ih.add_argument("--host", default="all", choices=["all", "openclaw", "hermes", "claude"])
    ih.add_argument("--write", action="store_true",
                    help="apply (merge host config + create skill symlinks); default prints a dry-run report")
    ih.set_defaults(fn=_cmd_install_host)

    ifa = sub.add_parser("install-for-agents",
                         help="one-shot: download references + wire hosts + verify (Genomi-style orchestrator)")
    ifa.add_argument("--subject", required=True)
    ifa.add_argument("--user-dir", required=True)
    ifa.add_argument("--host", default="all", choices=["all", "openclaw", "hermes", "claude"])
    ifa.add_argument("--libraries", nargs="*", help="reference library ids; empty/'everything' = phase-A core")
    ifa.add_argument("--write", action="store_true", help="perform it (download + wire); default is a dry-run")
    ifa.add_argument("--force", action="store_true", help="re-download already-installed libraries")
    ifa.add_argument("--skip-verify", action="store_true")
    ifa.set_defaults(fn=_cmd_install_for_agents)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
