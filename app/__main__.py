"""Command-line entry point.

    python3 -m app                       start the web UI on http://127.0.0.1:8765
    python3 -m app serve --port 9000     same, on another port
    python3 -m app validate              validate the saved configuration (runs no compiler)
    python3 -m app run                   build + test with the saved configuration, write report
    python3 -m app report RUN_ID [--sample --out FILE]   re-render the report of a recorded run
    python3 -m app export [--out DIR]    write the static website (history, reports, tests, source)
"""

import argparse
import ipaddress
import sys

from . import TOOL_NAME, config as config_mod, report, service, site, store


def cmd_validate(_args):
    cfg = config_mod.load_config()
    checks = config_mod.validate_environment(cfg)
    for c in checks:
        print(f"[{c['status'].upper():7}] {c['name']}: {c['message']}")
    return 1 if any(c["status"] == "error" for c in checks) else 0


def cmd_run(_args):
    cfg = config_mod.load_config()
    run = service.run_and_record(cfg, on_progress=lambda m: print(f"... {m}"))
    s = run["summary"]
    print(f"\nRun {run['run_id']}: {run['status']}")
    print(f"Build: {run['build']['status']} (exit code {run['build']['exit_code']})")
    print(f"Tests: {s['passed']} passed, {s['failed']} failed, {s['errors']} errors, "
          f"{s['not_run']} not run, {s['total']} total")
    for t in run["tests"]:
        if t["status"] != "PASS":
            print(f"  {t['status']:8} {t['id']}: {'; '.join(t['reasons'])}")
    for note in run["notes"]:
        print(f"Note: {note}")
    print(f"Record: runs/{run['run_id']}.json")
    print(f"Report: {run.get('report_file') or 'not written'}")
    return 0 if run["status"] in ("PASSED", "PASSED_WITH_SKIPS") else 1


def cmd_report(args):
    run = store.load_run(args.run_id)
    if run is None:
        print(f"No recorded run '{args.run_id}' in runs/", file=sys.stderr)
        return 1
    if args.out:
        out = config_mod.resolve_in_root(config_mod.PROJECT_ROOT, args.out)
        if out is None:
            print("--out must be inside the project directory", file=sys.stderr)
            return 1
        path = report.write_report(run, out.parent, sample=args.sample, filename=out.name)
    else:
        path = report.write_report(run, config_mod.resolved_paths(run["config"])["report_dir"], sample=args.sample)
    print(f"Report written: {path}")
    return 0


def cmd_export(args):
    cfg = config_mod.load_config()
    out = config_mod.resolve_in_root(config_mod.PROJECT_ROOT, args.out)
    if out is None or out == config_mod.PROJECT_ROOT:
        print("--out must be a folder inside the project directory", file=sys.stderr)
        return 1
    runs = [store.load_run(r["run_id"]) for r in store.list_runs(limit=site.MAX_RUNS)]
    site.export_site([r for r in runs if r], cfg, out)
    print(f"Static site written: {out} ({len(runs)} run(s))")
    return 0


def cmd_serve(args):
    from .server import make_server
    try:
        loopback = args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        print("WARNING: binding to a non-loopback address exposes a tool that runs a compiler. "
              "This v1 is meant for local trusted use only.", file=sys.stderr)
    httpd = make_server(args.host, args.port)
    port = httpd.server_address[1]
    print(f"{TOOL_NAME} running")
    print(f"  Configuration: http://{args.host}:{port}/config")
    print(f"  Results:       http://{args.host}:{port}/results")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m app", description=TOOL_NAME)
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="start the web UI (default)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("validate", help="validate the saved configuration")
    sub.add_parser("run", help="build and test with the saved configuration")
    rep = sub.add_parser("report", help="re-render the HTML report of a recorded run")
    rep.add_argument("run_id")
    rep.add_argument("--sample", action="store_true", help="label the report as a SAMPLE")
    rep.add_argument("--out", help="output file inside the project (default: report dir)")
    exp = sub.add_parser("export", help="write the static website for publishing")
    exp.add_argument("--out", default="site", help="output folder inside the project (default: site)")
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve"])
    try:
        return {"serve": cmd_serve, "validate": cmd_validate, "run": cmd_run, "report": cmd_report,
                "export": cmd_export}[args.command](args)
    except config_mod.ConfigError as exc:
        print("Configuration error:\n  " + "\n  ".join(exc.errors), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
