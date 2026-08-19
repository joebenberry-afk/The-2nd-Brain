
"""Deterministic inventory (AST-based): module -> symbols, CLI wiring, tests, internal refs."""
import ast, json, pathlib, re
root = pathlib.Path(__file__).resolve().parents[3]
src = root / "src" / "second_brain"; tests = root / "tests"

def imported_modules(path):
    """Set of second_brain submodule names imported anywhere in this file (any syntax)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    got = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level and not mod:                       # from . import a, b
                got.update(a.name for a in n.names)
            elif mod.startswith("second_brain") or n.level:
                parts = mod.split(".")
                tail = parts[-1] if parts[-1] != "second_brain" else None
                if mod in ("second_brain",):              # from second_brain import a, b
                    got.update(a.name for a in n.names)
                elif tail:
                    got.add(tail)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("second_brain."):
                    got.add(a.name.split(".")[1])
    return got

mods = sorted(f.stem for f in src.glob("*.py") if not f.stem.startswith("__"))
cli_imports = imported_modules(src / "cli.py")
test_imports = {t.name: imported_modules(t) for t in sorted(tests.glob("test_*.py"))}
test_counts = {t.name: len(re.findall(r"^\s*def test_", t.read_text(encoding="utf-8"), re.M))
               for t in sorted(tests.glob("test_*.py"))}
mod_imports = {m: imported_modules(src / f"{m}.py") for m in mods}
out = {}
for m in mods:
    text = (src / f"{m}.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    syms = [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.name.startswith("_")]
    ts = [{"file": tn, "test_funcs": test_counts[tn]} for tn, imps in test_imports.items() if m in imps]
    out[m] = {
        "loc": text.count("\n") + 1,
        "n_public": len(syms), "public_symbols": syms,
        "imported_by_cli": m in cli_imports,
        "imported_by_modules": sorted(o for o in mods if o != m and m in mod_imports[o]),
        "tests": ts, "n_test_files": len(ts),
        "n_test_funcs": sum(t["test_funcs"] for t in ts),
    }
print(json.dumps(out, indent=1))
