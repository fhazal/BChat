"""The QA runner (tools/qa.py) itself: status rules, exit codes, reports, interruption, locks.

Fake stages run tiny Python children, so nothing here needs a build or a network.
"""
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("qa_runner", ROOT / "tools" / "qa.py")
qa = importlib.util.module_from_spec(_spec)
sys.modules["qa_runner"] = qa
_spec.loader.exec_module(qa)
PY = sys.executable


def meta():
    env = {"source": {"commit": "abc", "branch": "main", "uncommitted_files": 0, "dirty": False},
           "app": {"exe": "x", "exists": False, "version": "", "exe_sha256": "", "exe_bytes": 0},
           "build_config": {"pyinstaller": "-", "pyside6": "-", "freeze_recipe_sha256": ""},
           "machine": {"python": "-", "windows": "-", "cpu": "-", "ram_gb": "-", "gpu": "-"}}
    return {"run_id": "t", "command": "test", "stages_requested": [], "started": "-", "environment": env}


def code(src):
    return [PY, "-c", textwrap.dedent(src)]


def go(tmp_path, stages):
    run_dir = tmp_path / "run"
    (run_dir / "results").mkdir(parents=True)
    rc = qa.run(stages, run_dir, meta(), tmp_path / ".heavy.lock")
    return rc, json.loads((run_dir / "report.json").read_text()), (run_dir / "summary.md").read_text()


def test_pass_and_fail_give_the_right_exit_code_and_keep_logs(tmp_path):
    ok = qa.Stage("a", "passes", steps=[qa.Step("ok", code("import sys; print('hello out'); print('hello err', file=sys.stderr)"))])
    bad = qa.Stage("b", "fails", steps=[qa.Step("bad", code("raise SystemExit(3)"))])
    rc, rep, summary = go(tmp_path, [ok, bad])
    assert rc == 1 and rep["overall"] == "FAIL"
    a, b = rep["stages"]
    assert a["status"] == "PASS" and b["status"] == "FAIL" and b["steps"][0]["exit_code"] == 3
    assert "hello out" in Path(a["steps"][0]["stdout_log"]).read_text()
    assert "hello err" in Path(a["steps"][0]["stderr_log"]).read_text()
    assert "**Overall: FAIL**" in summary
    rc, rep, _ = go(tmp_path / "2", [qa.Stage("a", "passes", steps=[qa.Step("ok", code("pass"))])])
    assert rc == 0 and rep["overall"] == "PASS"


def test_skipped_stage_is_never_a_pass(tmp_path):
    rc, rep, _ = go(tmp_path, [qa.Stage("perf", "x", mandatory=False, skip_reason="not built yet")])
    assert rc == 1 and rep["overall"] == "NO RESULT" and rep["stages"][0]["status"] == "SKIP"
    rc, rep, summary = go(tmp_path / "2", [qa.Stage("a", "x", steps=[qa.Step("ok", code("pass"))]),
                                           qa.Stage("perf", "x", mandatory=False, skip_reason="not built yet")])
    assert rc == 0 and [s["status"] for s in rep["stages"]] == ["PASS", "SKIP"]
    assert "| perf (optional) | **SKIP** |" in summary


def test_missing_package_or_tool_is_not_run_and_fails_the_run(tmp_path):
    dep = qa.Stage("a", "x", steps=[qa.Step("s", code("pass"), needs=["no_such_module_for_qa_test"])])
    tool = qa.Stage("b", "x", steps=[qa.Step("s", code("pass"), needs_files=[tmp_path / "gone.py"])])
    rc, rep, _ = go(tmp_path, [dep, tool])
    assert rc == 1 and rep["overall"] == "FAIL"
    assert rep["stages"][0]["status"] == "NOT RUN" and "no_such_module_for_qa_test" in rep["stages"][0]["reason"]
    assert rep["stages"][1]["status"] == "NOT RUN" and "gone.py" in rep["stages"][1]["reason"]


def test_missing_exe_through_the_command_line(tmp_path):
    rc = qa.main(["packaged", "build-check", "--exe", str(tmp_path / "nope" / "BChat.exe")], reports_root=tmp_path)
    run = next(p for p in tmp_path.iterdir() if p.is_dir())
    rep = json.loads((run / "report.json").read_text())
    assert rc == 1 and rep["overall"] == "FAIL"
    assert {s["name"]: s["status"] for s in rep["stages"]} == {"build-check": "NOT RUN", "packaged": "NOT RUN"}
    assert all("no BChat.exe" in s["reason"] for s in rep["stages"])


def test_timeout_kills_the_child(tmp_path):
    st = qa.Step("slow", code("import time; time.sleep(30)"), timeout=1)
    t0 = time.time()
    rc, rep, _ = go(tmp_path, [qa.Stage("a", "x", steps=[st])])
    assert rc == 1 and time.time() - t0 < 15
    assert rep["stages"][0]["steps"][0]["status"] == "FAIL" and "timed out" in rep["stages"][0]["steps"][0]["reason"]


def test_tool_result_with_failures_fails_even_with_exit_0_and_old_results_are_not_reused(tmp_path):
    res = tmp_path / "r.json"
    lying = qa.Step("t", code(f"import json; json.dump({{'ok': 5, 'fail': 1, 'skip': 0, 'failed': ['x']}}, open({str(res)!r}, 'w'))"),
                    result_json=res)
    rc, rep, _ = go(tmp_path, [qa.Stage("a", "x", steps=[lying])])
    assert rc == 1 and rep["stages"][0]["status"] == "FAIL"
    res.write_text(json.dumps({"ok": 9, "fail": 0, "skip": 0}))          # a result from an earlier run
    silent = qa.Step("t", code("pass"), result_json=res)
    rc, rep, _ = go(tmp_path / "2", [qa.Stage("a", "x", steps=[silent])])
    assert rc == 1 and "wrote no result file" in rep["stages"][0]["steps"][0]["reason"]


def test_skips_inside_a_tool_are_reported(tmp_path):
    res = tmp_path / "r.json"
    st = qa.Step("t", code(f"import json; json.dump({{'ok': 3, 'fail': 0, 'skip': 2}}, open({str(res)!r}, 'w'))"), result_json=res)
    rc, rep, _ = go(tmp_path, [qa.Stage("a", "x", steps=[st])])
    assert rc == 0 and "2 check(s) skipped" in rep["stages"][0]["steps"][0]["reason"]


def test_known_flaky_failure_is_labelled_not_retried(tmp_path, monkeypatch):
    tdir = tmp_path / "t"
    tdir.mkdir()
    counter = tmp_path / "runs.txt"
    (tdir / "test_flaky_one.py").write_text(textwrap.dedent(f"""
        def test_wobbly():
            with open({str(counter)!r}, "a") as f:
                f.write("x")
            assert False
    """))
    junit = tmp_path / "j.xml"
    st = qa.Step("pytest", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", str(tdir / "test_flaky_one.py")],
                 junit=junit, needs=["pytest"])
    rc, rep, summary = go(tmp_path, [qa.Stage("tests", "x", steps=[st])])
    failed = rep["stages"][0]["steps"][0]["details"]["failed_tests"]
    assert rc == 1 and len(failed) == 1
    monkeypatch.setitem(qa.KNOWN_FLAKY, failed[0], {"test": failed[0], "why": "test reason"})
    rc, rep, summary = go(tmp_path / "2", [qa.Stage("tests", "x", steps=[st])])
    assert rc == 1 and rep["overall"] == "FAIL"                       # still a failure
    assert "Known flaky tests that failed (not retried; still a failure)" in summary and "test reason" in summary
    assert counter.read_text() == "xx"                                 # ran once per QA run: no retry


def test_coverage_drop_is_a_warning(tmp_path, monkeypatch):
    res = tmp_path / "r.json"
    st = qa.Step("t", code(f"import json; json.dump({{'ok': 3, 'fail': 0, 'skip': 0}}, open({str(res)!r}, 'w'))"),
                 result_json=res, baseline_key="k")
    monkeypatch.setitem(qa.BASELINE, "k", 10)
    rc, rep, summary = go(tmp_path, [qa.Stage("a", "x", steps=[st])])
    assert rc == 0 and any("fewer than before" in w for w in rep["warnings"]) and "## Warnings" in summary


def test_heavy_lock_stops_a_second_heavy_run(tmp_path):
    held = qa.HeavyLock(tmp_path / ".heavy.lock")
    assert held.acquire() == ""
    try:
        light = qa.Stage("a", "x", steps=[qa.Step("ok", code("pass"))])
        heavy = qa.Stage("b", "x", heavy=True, steps=[qa.Step("ok", code("pass"))])
        rc, rep, _ = go(tmp_path, [light, heavy])
    finally:
        held.release()
    assert rc == 1
    assert rep["stages"][0]["status"] == "PASS"
    assert rep["stages"][1]["status"] == "NOT RUN" and "heavy-job lock" in rep["stages"][1]["reason"]


WRAPPER = r'''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("qa_runner", r"{qa}")
qa = importlib.util.module_from_spec(spec); sys.modules["qa_runner"] = qa; spec.loader.exec_module(qa)
sys.path.insert(0, r"{tests}")
from test_qa_runner import meta
run_dir = Path(r"{run}"); (run_dir / "results").mkdir(parents=True)
slow = qa.Step("slow", [sys.executable, "-c", "import os, time; open(r'{pid}', 'w').write(str(os.getpid())); time.sleep(60)"])
later = qa.Stage("later", "x", steps=[qa.Step("ok", [sys.executable, "-c", "pass"])])
sys.exit(qa.run([qa.Stage("first", "x", steps=[slow]), later], run_dir, meta(), Path(r"{lock}")))
'''


def _start_wrapper(tmp_path):
    w = tmp_path / "w.py"
    run, pid = tmp_path / "run", tmp_path / "child.pid"
    fwd = lambda x: str(x).replace("\\", "/")          # forward slashes: no escapes inside the generated script
    w.write_text(WRAPPER.format(qa=fwd(ROOT / "tools" / "qa.py"), tests=fwd(ROOT / "tests"), run=fwd(run), pid=fwd(pid),
                                lock=fwd(tmp_path / ".l")))
    p = subprocess.Popen([PY, str(w)], cwd=tmp_path, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 30
    while not pid.exists() and time.time() < end:
        time.sleep(0.1)
    assert pid.exists(), "the slow child never started"
    time.sleep(0.5)
    return p, run, int(pid.read_text())


def _alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_interrupt_gives_interrupted_report_and_kills_the_child(tmp_path):
    import signal
    p, run, child = _start_wrapper(tmp_path)
    p.send_signal(signal.CTRL_BREAK_EVENT)
    assert p.wait(30) == 130
    rep = json.loads((run / "report.json").read_text())
    assert rep["overall"] == "INTERRUPTED"
    first, later = rep["stages"]
    assert first["steps"][0]["status"] == "FAIL" and "interrupted" in first["steps"][0]["reason"]
    assert later["status"] == "NOT RUN"
    assert "do not trust this report" in (run / "summary.md").read_text()
    time.sleep(1)
    assert not _alive(child)


def test_hard_kill_leaves_an_incomplete_report_never_pass(tmp_path):
    p, run, child = _start_wrapper(tmp_path)
    p.kill()
    p.wait(30)
    rep = json.loads((run / "report.json").read_text())
    assert rep["overall"] == "INCOMPLETE"
    assert "Overall: INCOMPLETE" in (run / "summary.md").read_text()
    subprocess.run(["taskkill", "/F", "/PID", str(child)], capture_output=True)   # the orphan sleeper


def test_lock_works_across_processes_and_frees_when_the_holder_dies(tmp_path):
    lock = str(tmp_path / ".heavy.lock").replace("\\", "/")
    qa_path = str(ROOT / "tools" / "qa.py").replace("\\", "/")
    holder = subprocess.Popen([PY, "-c", textwrap.dedent(f"""
        import importlib.util, sys, time
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("qa_runner", "{qa_path}")
        qa = importlib.util.module_from_spec(spec); sys.modules["qa_runner"] = qa; spec.loader.exec_module(qa)
        held = qa.HeavyLock(Path("{lock}"))          # keep the object: closing the file would free the lock
        assert held.acquire() == ""
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    mine = qa.HeavyLock(tmp_path / ".heavy.lock")
    why = mine.acquire()
    assert "heavy-job lock" in why and f"pid {holder.pid}" in why
    holder.kill()
    holder.wait(10)
    time.sleep(0.5)
    assert mine.acquire() == ""                                        # Windows freed it with the dead process
    mine.release()
