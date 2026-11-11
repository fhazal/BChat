"""BChat QA runner: one entry point that runs the independent QA tools and writes one report.

    python tools/qa.py --list
    python tools/qa.py tests
    python tools/qa.py packaged --exe dist/BChat/BChat.exe
    python tools/qa.py tests packaged
    python tools/qa.py all --exe dist/BChat/BChat.exe

The runner only orchestrates: every stage calls existing tools (pytest, tools/qa/*.py, dev-tools/*.py) as child
processes, keeps their stdout/stderr, exit code and time, and reads their JSON or JUnit results. Stage status:
PASS, FAIL, SKIP (deliberately not run, with the reason) or NOT RUN (couldn't run: missing exe, tool, package,
heavy-job lock, interruption). SKIP and NOT RUN are never counted as passed.

Report: qa-reports/<yyyymmdd-hhmmss>/report.json + summary.md + logs/ + results/. report.json is written at the
start as INCOMPLETE and rewritten after every step, so a crash or kill leaves INCOMPLETE, never PASS.
Exit code: 0 = every mandatory stage that ran passed and none was NOT RUN; 1 = failure or nothing ran;
2 = bad arguments; 130 = interrupted.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.metadata
import importlib.util
import json
import os
import platform
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "tools" / "qa"
sys.path.insert(0, str(QA))
from qa_common import exe_version, sha256  # noqa: E402

DATA = QA / "data"
ORDER = ["build-check", "tests", "protocol", "irc", "audit", "packaged", "ui", "perf"]
IRC_TESTS = ["tests/test_live.py", "tests/test_040.py", "tests/test_060.py", "tests/test_060c.py",
             "tests/test_safety.py", "tests/test_comfort.py", "tests/test_welcome.py", "tests/test_qa_ircd.py"]
PROTOCOL_TESTS = ["tests/test_core.py", "tests/test_irclink.py", "tests/test_conformance.py"]


@dataclass
class Step:
    name: str
    cmd: list[str]
    timeout: int = 600
    needs: list[str] = field(default_factory=list)       # Python modules the child needs
    needs_files: list[Path] = field(default_factory=list)
    result_json: Path | None = None                      # tools/qa JSON result written by the child
    junit: Path | None = None                            # pytest --junitxml file
    parse_stdout: object = None                          # callable(stdout) -> (status, details) for tools without JSON
    baseline_key: str = ""
    status: str = "NOT RUN"
    reason: str = "not started"
    exit_code: int | None = None
    seconds: float = 0.0
    details: dict = field(default_factory=dict)
    stdout_log: str = ""
    stderr_log: str = ""


@dataclass
class Stage:
    name: str
    title: str
    mandatory: bool = True
    heavy: bool = False
    steps: list[Step] = field(default_factory=list)
    skip_reason: str = ""          # set = SKIP on purpose (not built yet, included in another stage)
    not_run_reason: str = ""       # set = NOT RUN (can't run here)
    status: str = "NOT RUN"
    reason: str = "not started"
    seconds: float = 0.0


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


KNOWN_FLAKY = {x["test"]: x for x in load_json(DATA / "known-flaky.json", {"tests": []})["tests"]}
BASELINE = load_json(DATA / "baseline.json", {})


# ---- stage plan -----------------------------------------------------------------------------------------------

def button_check_status(stdout: str):
    """full_button_check.py always exits 0; its last lines say 'no problems' or 'PROBLEMS:'."""
    controls = None
    for ln in stdout.splitlines():
        if ln.startswith("clicked or changed "):
            try:
                controls = int(ln.split()[3])
            except (IndexError, ValueError):
                pass
    if "PROBLEMS:" in stdout:
        return "FAIL", {"controls": controls, "problems": stdout.split("PROBLEMS:", 1)[1].strip()[:2000]}
    if "no problems" in stdout:
        return "PASS", {"controls": controls}
    return "FAIL", {"controls": controls, "problems": "the tool ended without its 'no problems' / 'PROBLEMS:' line"}


def plan(names: list[str], a, run_dir: Path) -> list[Stage]:
    py = sys.executable
    res = run_dir / "results"
    exe = Path(a.exe)
    exe_ok = exe.exists()
    common = ["--exe", str(exe)] + (["--expect", a.expect] if a.expect else [])
    stages: dict[str, Stage] = {}

    def pytest_step(name, targets, timeout):
        junit = res / f"{name}.junit.xml"
        return Step(name, [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *targets],
                    timeout=timeout, needs=["pytest", "PySide6"], junit=junit, baseline_key=f"pytest:{name}")

    stages["tests"] = Stage("tests", "Full source test suite (unit, integration, UI)",
                            steps=[pytest_step("pytest", ["tests"], 2400)])
    stages["protocol"] = Stage("protocol", "IRC/IRCv3 conformance tests + the status table (docs/PROTOCOL-CONFORMANCE.md)",
                               steps=[pytest_step("pytest-protocol", PROTOCOL_TESTS, 600),
                                      Step("conformance_report", [py, str(QA / "conformance_report.py"),
                                                                  "--junit", str(res / "pytest.junit.xml"),
                                                                  "--junit", str(res / "pytest-protocol.junit.xml"),
                                                                  "--out", str(ROOT / "docs" / "PROTOCOL-CONFORMANCE.md"),
                                                                  "--json", str(res / "conformance.json")],
                                           timeout=120, needs_files=[QA / "conformance_report.py"],
                                           result_json=res / "conformance.json")])
    stages["irc"] = Stage("irc", "IRC integration tests against the local fake server",
                          steps=[pytest_step("pytest-irc", IRC_TESTS, 1800)])
    if "tests" in names:                       # protocol still runs: it is quick and writes the conformance table
        stages["irc"].skip_reason = "included in the 'tests' stage (same test files)"

    btn = ROOT / "dev-tools" / "full_button_check.py"
    stages["ui"] = Stage("ui", "Every control in every window (real widgets)", heavy=True, steps=[
        Step("full_button_check", [py, str(btn), str(res / "ui")], timeout=1200, needs=["PySide6"],
             needs_files=[btn], parse_stdout=button_check_status, baseline_key="ui:controls")])

    pk = []
    for tool, t in (("bundle_check", 120), ("frozen_check", 600), ("frozen_features", 600),
                    ("frozen_reports", 600), ("frozen_extra", 900)):
        pk.append(Step(tool, [py, str(QA / f"{tool}.py"), *common, "--out", str(res / "packaged")], timeout=t,
                       needs=["PySide6", "cryptography"] + (["PIL"] if tool == "frozen_check" else []),
                       needs_files=[QA / f"{tool}.py"], result_json=res / "packaged" / f"{tool}.json",
                       baseline_key=f"packaged:{tool}"))
    stages["packaged"] = Stage("packaged", "Packaged app: the built BChat.exe with throwaway settings", heavy=True, steps=pk)

    bc = [py, str(QA / "build_check.py"), *common, "--out", str(res / "build-check")]
    for opt in ("installer", "pyi_log", "iscc_log", "spec"):
        if getattr(a, opt):
            bc += [f"--{opt.replace('_', '-')}", getattr(a, opt)]
    stages["build-check"] = Stage("build-check", "Build: versions agree, installer and logs clean, build recipe recorded", steps=[
        Step("build_check", bc, timeout=120, needs_files=[QA / "build_check.py"],
             result_json=res / "build-check" / "build_check.json", baseline_key="build-check:build_check")])

    scan = ROOT / "dev-tools" / "secret_scan.py"
    stages["audit"] = Stage("audit", "Audit: secret scan of what git would commit (dependency/packaging audit: item G)", steps=[
        Step("secret_scan", [py, str(scan)], timeout=300, needs_files=[scan])])

    stages["perf"] = Stage("perf", "Performance benchmark of the packaged app on local servers, against the baseline",
                           heavy=True, steps=[
        Step("perf_bench", [py, str(QA / "perf_bench.py"), *common, "--out", str(res / "perf")]
             + (["--quick"] if a.perf_quick else []), timeout=2400, needs=["PySide6"],
             needs_files=[QA / "perf_bench.py", QA / "loadgen.py"], result_json=res / "perf" / "perf_bench.json")])

    for s in ("packaged", "build-check", "perf"):
        if not exe_ok:
            stages[s].not_run_reason = f"no BChat.exe at {exe} (build it, or pass --exe)"
    return [stages[n] for n in ORDER if n in names]


# ---- environment ----------------------------------------------------------------------------------------------

def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def ps(cmd: str) -> str:
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                              timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def version_of(pkg: str) -> str:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def environment(a) -> dict:
    exe = Path(a.exe)
    changed = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
    vi = (ROOT / "packaging" / "version_info.txt")
    spec = Path(a.spec) if a.spec else ROOT / "packaging" / "BChat.spec"
    return {
        "source": {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                   "uncommitted_files": len(changed), "dirty": bool(changed)},
        "app": {"exe": str(exe), "exists": exe.exists(), "version": exe_version(exe) if exe.exists() else "",
                "exe_sha256": sha256(exe) if exe.exists() else "",
                "exe_bytes": exe.stat().st_size if exe.exists() else 0},
        "build_config": {"freeze_recipe": str(spec), "freeze_recipe_sha256": sha256(spec) if spec.exists() else "",
                         "version_info_sha256": sha256(vi) if vi.exists() else "",
                         "pyinstaller": version_of("pyinstaller"), "pyside6": version_of("PySide6"),
                         "cryptography": version_of("cryptography"), "pyspellchecker": version_of("pyspellchecker"),
                         "pytest": version_of("pytest")},
        "machine": {"python": platform.python_version(), "python_exe": sys.executable, "windows": platform.platform(),
                    "cpu": ps("(Get-CimInstance Win32_Processor).Name"),
                    "ram_gb": ps("[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"),
                    "gpu": ps("(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name")},
    }


def other_test_instances() -> list[str]:
    """BChat.exe processes that are not the user's installed copy: another test run is busy."""
    installed = str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "BChat").lower()
    out = ps("Get-Process BChat -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }")
    return [p for p in out.splitlines() if p.strip() and not p.lower().startswith(installed)]


class HeavyLock:
    """One heavy QA job (packaged GUI checks, UI clicks, benchmarks) at a time on this PC."""

    def __init__(self, path: Path):
        self.path, self.fh = path, None

    def acquire(self) -> str:
        """Lock byte 0 of the lock file (Windows releases it when the process dies). Who holds it is written to a
        separate .info file, because a locked byte can't be read by anyone else."""
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        info = self.path.with_suffix(".info")
        self.fh = open(self.path, "a+b")
        self.fh.seek(0)                                    # locking() starts at the file position: always byte 0
        try:
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.fh.close()
            self.fh = None
            try:
                holder = info.read_text(encoding="utf-8").strip()
            except OSError:
                holder = ""
            return f"another QA run holds the heavy-job lock ({holder or 'holder unknown'})"
        info.write_text(f"pid {os.getpid()} since {datetime.datetime.now():%Y-%m-%d %H:%M:%S}", encoding="utf-8")
        return ""

    def release(self):
        if self.fh:
            import msvcrt
            try:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.fh.close()
            self.fh = None


# ---- running --------------------------------------------------------------------------------------------------

def kill_tree(p: subprocess.Popen):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)


def read_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed, skipped, xfailed = [], [], []
    for case in root.iter("testcase"):
        tid = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name')}"
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(tid)
        elif case.find("skipped") is not None:
            sk = case.find("skipped")
            (xfailed if "xfail" in (sk.get("type", "") + sk.get("message", "")).lower() else skipped).append(tid)
    flaky = [t for t in failed if t in KNOWN_FLAKY]
    return {"total": total, "passed": total - len(failed) - len(skipped) - len(xfailed), "failed": len(failed),
            "skipped": len(skipped), "xfailed": len(xfailed), "xfailed_tests": xfailed, "failed_tests": failed, "failed_known_flaky": flaky,
            "failed_not_known_flaky": [t for t in failed if t not in KNOWN_FLAKY], "skipped_tests": skipped}


def run_step(st: Step, logs: Path, interrupted: list) -> None:
    missing = [m for m in st.needs if importlib.util.find_spec(m) is None]
    if missing:
        st.status, st.reason = "NOT RUN", "missing Python package(s): " + ", ".join(missing)
        return
    gone = [str(f) for f in st.needs_files if not Path(f).exists()]
    if gone:
        st.status, st.reason = "NOT RUN", "tool not found: " + ", ".join(gone)
        return
    if st.result_json and st.result_json.exists():
        st.result_json.unlink()                    # never read an old result as this run's
    if st.junit and st.junit.exists():
        st.junit.unlink()
    logs.mkdir(parents=True, exist_ok=True)
    out_p, err_p = logs / f"{st.name}.stdout.log", logs / f"{st.name}.stderr.log"
    st.stdout_log, st.stderr_log = str(out_p), str(err_p)
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with open(out_p, "w", encoding="utf-8") as so, open(err_p, "w", encoding="utf-8") as se:
        p = subprocess.Popen(st.cmd, cwd=ROOT, stdout=so, stderr=se, env=env,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            while p.poll() is None:
                if time.time() - t0 > st.timeout:
                    kill_tree(p)
                    p.wait()
                    st.exit_code, st.seconds = p.returncode, round(time.time() - t0, 1)
                    st.status, st.reason = "FAIL", f"timed out after {st.timeout} s (killed)"
                    return
                time.sleep(0.2)
        except KeyboardInterrupt:
            kill_tree(p)
            p.wait()
            st.exit_code, st.seconds = p.returncode, round(time.time() - t0, 1)
            st.status, st.reason = "FAIL", "interrupted (Ctrl+C / Ctrl+Break); child process killed"
            interrupted.append(True)
            return
    st.exit_code, st.seconds = p.returncode, round(time.time() - t0, 1)
    stdout = out_p.read_text(encoding="utf-8", errors="replace")
    st.status = "PASS" if p.returncode == 0 else "FAIL"
    st.reason = f"exit code {p.returncode}"
    if st.junit:
        if st.junit.exists():
            st.details = read_junit(st.junit)
            if st.details["failed"] and st.status == "PASS":
                st.status, st.reason = "FAIL", "JUnit report lists failures"
            if st.details["failed"]:
                st.reason += f"; {st.details['failed']} failed ({len(st.details['failed_known_flaky'])} known flaky)"
        else:
            st.status, st.reason = "FAIL", st.reason + "; pytest wrote no JUnit report"
    if st.result_json:
        if st.result_json.exists():
            r = load_json(st.result_json, {})
            st.details = {k: r.get(k) for k in ("ok", "fail", "skip", "failed", "skipped", "exe_sha256", "exe_version", "seconds")}
            if r.get("fail") and st.status == "PASS":
                st.status, st.reason = "FAIL", "result lists failures"
        else:
            st.status, st.reason = "FAIL", st.reason + "; the tool wrote no result file"
    if st.parse_stdout:
        status, details = st.parse_stdout(stdout)
        st.details = details
        if status == "FAIL":
            st.status, st.reason = "FAIL", "the tool reported problems"
    if st.status == "PASS" and st.details.get("skip"):
        st.reason += f"; {st.details['skip']} check(s) skipped inside the tool (listed in its result)"


def coverage_warnings(stages: list[Stage]) -> list[str]:
    """Fewer tests/checks than the baseline can mean coverage was lost: say so (it doesn't fail the run)."""
    warn = []
    for s in stages:
        for st in s.steps:
            want = BASELINE.get(st.baseline_key)
            if not want or st.status not in ("PASS", "FAIL"):
                continue
            have = st.details.get("total") if st.junit else st.details.get("controls") if st.parse_stdout else \
                (st.details.get("ok", 0) or 0) + (st.details.get("fail", 0) or 0) + (st.details.get("skip", 0) or 0)
            if isinstance(have, int) and have < want:
                warn.append(f"{s.name}/{st.name}: {have} checks, baseline {want}: fewer than before, find out why")
            elif isinstance(have, int) and have > want:
                warn.append(f"{s.name}/{st.name}: {have} checks, baseline {want} (more: update tools/qa/data/baseline.json)")
    return warn


def overall(stages: list[Stage], interrupted: bool, finished: bool) -> str:
    if interrupted:
        return "INTERRUPTED"
    if not finished:
        return "INCOMPLETE"
    ran = [s for s in stages if s.status in ("PASS", "FAIL")]
    if any(s.mandatory and s.status in ("FAIL", "NOT RUN") for s in stages):
        return "FAIL"
    if not ran:
        return "NO RESULT"
    return "PASS"


def write_report(run_dir: Path, meta: dict, stages: list[Stage], state: str, warnings: list[str]) -> None:
    doc = dict(meta, overall=state, written=datetime.datetime.now().isoformat(timespec="seconds"), warnings=warnings,
               stages=[{"name": s.name, "title": s.title, "mandatory": s.mandatory, "heavy": s.heavy, "status": s.status,
                        "reason": s.reason, "seconds": s.seconds,
                        "steps": [{k: getattr(st, k) for k in ("name", "status", "reason", "exit_code", "seconds",
                                                                 "details", "stdout_log", "stderr_log")}
                                  | {"cmd": " ".join(st.cmd)} for st in s.steps]} for s in stages])
    tmp = run_dir / "report.json.tmp"
    tmp.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, run_dir / "report.json")
    env = meta["environment"]
    lines = [f"# BChat QA report {meta['run_id']}", "",
             f"**Overall: {state}**" + ("  (run not finished: do not trust this report)" if state in ("INCOMPLETE", "INTERRUPTED") else ""), "",
             f"- Command: `{meta['command']}`",
             f"- Source: `{env['source']['commit'][:12] or 'unknown'}` on `{env['source']['branch']}`"
             f"{' with ' + str(env['source']['uncommitted_files']) + ' uncommitted file(s)' if env['source']['dirty'] else ' (clean)'}",
             f"- App: `{env['app']['exe']}` version `{env['app']['version'] or '-'}` sha256 `{env['app']['exe_sha256'][:16] or '-'}`",
             f"- Build: PyInstaller {env['build_config']['pyinstaller']}, PySide6 {env['build_config']['pyside6']}, "
             f"recipe sha256 `{env['build_config']['freeze_recipe_sha256'][:16] or '-'}`",
             f"- Machine: Python {env['machine']['python']}, {env['machine']['windows']}, {env['machine']['cpu']}, "
             f"{env['machine']['ram_gb']} GB, {env['machine']['gpu']}", "",
             "| Stage | Status | Time | Details |", "| --- | --- | --- | --- |"]
    for s in stages:
        lines.append(f"| {s.name}{'' if s.mandatory else ' (optional)'} | **{s.status}** | {s.seconds:.0f} s | {s.reason} |")
        for st in s.steps:
            d = st.details
            counts = (f"{d.get('passed')}/{d.get('total')} passed, {d.get('failed')} failed, {d.get('skipped')} skipped, "
                      f"{d.get('xfailed', 0)} known deviation(s) (strict xfail)" if st.junit and d else
                      f"{d.get('ok')} OK, {d.get('fail')} FAIL, {d.get('skip')} SKIP" if st.result_json and d else
                      f"{d.get('controls')} controls" if st.parse_stdout and d else "")
            lines.append(f"| &nbsp;&nbsp;{st.name} | {st.status} | {st.seconds:.0f} s | {counts} {st.reason} |")
    flaky = [t for s in stages for st in s.steps for t in st.details.get("failed_known_flaky", [])]
    real = [t for s in stages for st in s.steps for t in st.details.get("failed_not_known_flaky", [])]
    failed_checks = [f"{s.name}/{st.name}: {x}" for s in stages for st in s.steps
                     if isinstance(st.details.get("failed"), list) for x in st.details["failed"]]   # pytest: a count
    if real or failed_checks:
        lines += ["", "## Failures", ""] + [f"- {t}" for t in real] + [f"- {t}" for t in failed_checks]
    if flaky:
        lines += ["", "## Known flaky tests that failed (not retried; still a failure)", ""] + \
                 [f"- {t}: {KNOWN_FLAKY[t].get('why', '')}" for t in flaky]
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    lines += ["", "Logs: `logs/<stage>/<step>.stdout.log` and `.stderr.log`; tool results: `results/`."]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(stages: list[Stage], run_dir: Path, meta: dict, lock_path: Path) -> int:
    interrupted: list = []
    lock = HeavyLock(lock_path)
    lock_problem = ""
    if any(s.heavy and not s.skip_reason and not s.not_run_reason for s in stages):
        lock_problem = lock.acquire()
        busy = other_test_instances() if not lock_problem else []
        if busy:
            lock_problem = "another BChat test instance is running: " + "; ".join(busy)
    write_report(run_dir, meta, stages, "INCOMPLETE", [])

    def on_break(*_):
        raise KeyboardInterrupt
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_break)
    try:
        for s in stages:
            if interrupted:
                s.status, s.reason = "NOT RUN", "the run was interrupted before this stage"
                continue
            if s.skip_reason:
                s.status, s.reason = "SKIP", s.skip_reason
                for st in s.steps:
                    st.status, st.reason = "SKIP", s.skip_reason
                print(f"[{s.name}] SKIP: {s.skip_reason}", flush=True)
                continue
            if s.not_run_reason or (s.heavy and lock_problem):
                s.status, s.reason = "NOT RUN", s.not_run_reason or lock_problem
                for st in s.steps:
                    st.status, st.reason = "NOT RUN", s.reason
                print(f"[{s.name}] NOT RUN: {s.reason}", flush=True)
                write_report(run_dir, meta, stages, "INCOMPLETE", [])
                continue
            t0 = time.time()
            print(f"[{s.name}] {s.title}", flush=True)
            for st in s.steps:
                if interrupted:
                    st.status, st.reason = "NOT RUN", "the run was interrupted before this step"
                    continue
                try:
                    run_step(st, run_dir / "logs" / s.name, interrupted)
                except KeyboardInterrupt:          # Ctrl+C between two steps
                    interrupted.append(True)
                    st.status, st.reason = "NOT RUN", "the run was interrupted before this step"
                print(f"  {st.name}: {st.status} ({st.reason})", flush=True)
                write_report(run_dir, meta, stages, "INCOMPLETE", [])
            s.seconds = round(time.time() - t0, 1)
            statuses = [st.status for st in s.steps]
            if "FAIL" in statuses:
                s.status, s.reason = "FAIL", "; ".join(f"{st.name}: {st.reason}" for st in s.steps if st.status == "FAIL")
            elif "NOT RUN" in statuses:
                s.status, s.reason = "NOT RUN", "; ".join(f"{st.name}: {st.reason}" for st in s.steps if st.status == "NOT RUN")
            else:
                s.status, s.reason = "PASS", f"{len(s.steps)} step(s) passed"
    except KeyboardInterrupt:
        interrupted.append(True)
        for s in stages:
            if s.status == "NOT RUN" and s.reason == "not started":
                s.reason = "the run was interrupted before this stage"
    finally:
        lock.release()
    state = overall(stages, bool(interrupted), True)
    warnings = coverage_warnings(stages)
    write_report(run_dir, meta, stages, state, warnings)
    print(f"\nOVERALL: {state}   report: {run_dir / 'summary.md'}", flush=True)
    for w in warnings:
        print("WARNING:", w)
    return 130 if state == "INTERRUPTED" else 0 if state == "PASS" else 1


def main(argv=None, reports_root: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Stages: " + ", ".join(ORDER) + ", all")
    ap.add_argument("stages", nargs="*")
    ap.add_argument("--list", action="store_true", help="show the stages and what they run")
    ap.add_argument("--exe", default=str(ROOT / "dist" / "BChat" / "BChat.exe"))
    ap.add_argument("--expect", default="", help="version the exe must report (default: its own version resource)")
    ap.add_argument("--installer", default="")
    ap.add_argument("--pyi-log", dest="pyi_log", default="")
    ap.add_argument("--iscc-log", dest="iscc_log", default="")
    ap.add_argument("--spec", default="")
    ap.add_argument("--perf-quick", action="store_true", help="perf stage: short smoke run (not for comparisons)")
    ap.add_argument("--reports", default=str(reports_root or ROOT / "qa-reports"))
    a = ap.parse_args(argv)
    a.exe = str(Path(a.exe).resolve())
    names = list(dict.fromkeys(a.stages))
    if "all" in names:
        names = ["build-check", "tests", "protocol", "irc", "audit", "packaged", "ui", "perf"]
    bad = [n for n in names if n not in ORDER]
    if a.list or not names or bad:
        if bad:
            print("unknown stage(s):", ", ".join(bad), file=sys.stderr)
        tmp = Path(a.reports) / "_list"
        listed = {s.name: s for s in plan([n for n in ORDER if n != "tests"], a, tmp) + plan(["tests"], a, tmp)}
        for s in (listed[n] for n in ORDER):
            print(f"{s.name:12} {'mandatory' if s.mandatory else 'optional '} {'heavy' if s.heavy else '     '}  {s.title}"
                  + (f"  [SKIP: {s.skip_reason}]" if s.skip_reason else ""))
        return 2 if bad or not (a.list or names) else 0
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(a.reports) / run_id
    n = 1
    while run_dir.exists():
        n += 1
        run_dir = Path(a.reports) / f"{run_id}-{n}"
    (run_dir / "results").mkdir(parents=True)
    stages = plan(names, a, run_dir)
    meta = {"run_id": run_dir.name, "command": "python tools/qa.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "stages_requested": names, "started": datetime.datetime.now().isoformat(timespec="seconds"),
            "environment": environment(a)}
    return run(stages, run_dir, meta, Path(a.reports) / ".heavy.lock")


if __name__ == "__main__":
    sys.exit(main())
