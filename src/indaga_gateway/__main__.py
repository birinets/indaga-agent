"""Gateway entry point.

    python -m indaga_gateway serve         # run the HTTP server (uvicorn)
    python -m indaga_gateway pair-code      # mint + print a one-time pairing code for the phone

Subject / bind address / port come from the environment (see config.Settings):
    INDAGA_SUBJECT, INDAGA_USER_DIR, INDAGA_GATEWAY_HOST, INDAGA_GATEWAY_PORT.
On a reachable server, bind to the Tailscale interface (not 0.0.0.0) and never set
INDAGA_GATEWAY_ALLOW_INSECURE.
"""

from __future__ import annotations

import argparse

from .config import Settings


def _cmd_serve(args) -> int:
    import uvicorn

    from .app import create_app

    settings = Settings.from_env()
    app = create_app(settings)
    if settings.allow_insecure:
        print("[indaga-gateway] WARNING: INSECURE mode (auth disabled) — local dev only.")
    print(f"[indaga-gateway] serving subject={settings.subject!r} on http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


def _cmd_pair_code(args) -> int:
    from . import auth

    settings = Settings.from_env()
    code = auth.mint_pairing_code(settings.subject)
    print(f"Pairing code for subject {settings.subject!r} (valid 10 minutes): {code}")
    print("Enter it in the Indaga app to pair this device.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="indaga-gateway")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the HTTP gateway").set_defaults(fn=_cmd_serve)
    sub.add_parser("pair-code", help="mint a one-time pairing code for a new device").set_defaults(fn=_cmd_pair_code)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
