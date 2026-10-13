import ast
import sys
from pathlib import Path

from engine import DECIDE_LIMIT_MS, load_bot_class, play_match

HERE = Path(__file__).resolve().parent
BOT_FILE = HERE / "my_bot.py"
SPARRING_FILE = HERE / "sparring.py"
BANNED_MODULES = {"os", "sys", "subprocess", "socket", "pickle", "threading", "time",
                  "importlib", "builtins", "ctypes"}
BANNED_CALLS = {"eval", "exec", "open", "compile", "input", "__import__"}


def import_problem(name, line):
    top = name.split(".")[0]
    if top == "vibe_sdk" or (top in sys.stdlib_module_names and top not in BANNED_MODULES):
        return []
    return [f"line {line}: import of '{top}' is not allowed"]


def static_problems(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}"]
    problems = []
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    if "MyBot" not in classes:
        problems.append("no class named MyBot")
    elif not any(isinstance(n, ast.FunctionDef) and n.name == "decide" for n in classes["MyBot"].body):
        problems.append("MyBot has no decide(view) method")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                problems += import_problem(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f"line {node.lineno}: relative imports are not allowed")
            else:
                problems += import_problem(node.module or "", node.lineno)
            if node.module == "random" and any(a.name != "Random" for a in node.names):
                problems.append(f"line {node.lineno}: use random.Random(seed), not module-level random")
        elif isinstance(node, ast.Name) and node.id in BANNED_CALLS:
            problems.append(f"line {node.lineno}: {node.id}() is not allowed")
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
              and node.value.id == "random" and node.attr != "Random"):
            problems.append(f"line {node.lineno}: random.{node.attr} is unseeded; use random.Random(seed)")
    return problems


def you_row(result):
    return next(r for r in result["rows"] if r["id"] == 0)


def report(name, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main():
    problems = static_problems(BOT_FILE.read_text(encoding="utf-8"))
    results = [report("static rules", not problems, "; ".join(problems) or "clean")]
    if not all(results):
        sys.exit(1)

    you_cls = load_bot_class(BOT_FILE)
    spar_cls = load_bot_class(SPARRING_FILE)

    first = play_match(you_cls, you_cls, 7)
    second = play_match(you_cls, you_cls, 7)
    results.append(report("deterministic", first["log"] == second["log"],
                          "seed 7 replayed with identical turn logs"))

    rows = [you_row(play_match(you_cls, you_cls, s)) for s in range(1, 21)]
    illegal = sum(r["illegal"] for r in rows)
    bad = sum(r["bad_turns"] for r in rows)
    slowest = max(r["max_decide_ms"] for r in rows)
    results.append(report("legal actions", illegal == 0 and bad == 0,
                          f"20 maps vs copies, {illegal} illegal, {bad} bad turns"))
    results.append(report("speed", slowest < DECIDE_LIMIT_MS,
                          f"slowest decide {slowest:.2f} ms (limit {DECIDE_LIMIT_MS} ms)"))

    spar = [you_row(play_match(you_cls, spar_cls, s)) for s in range(1, 6)]
    spar_bad = sum(r["bad_turns"] for r in spar)
    results.append(report("robustness", spar_bad == 0,
                          f"5 maps vs sparring chaos bots, {spar_bad} bad turns of yours"))

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
