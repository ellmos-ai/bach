"""Module interdependency graph, derived from the source tree.

The circuit view is not a drawing of the architecture: it is the architecture. Every node is a
module that exists on disk and every edge is an `import` statement parsed out of it with `ast`,
so the diagram cannot drift away from the code the way a hand-maintained picture does. A module
that stops importing another loses the wire on the next page load.
"""

import ast
import os
from typing import Dict, List, Optional, Set, Tuple

PACKAGE = "sentinel_fleet"

# Pillar per top-level package. `web` is the composition root rather than a pillar, so it is
# drawn neutral: it wires the others together and owns none of their concerns.
PILLAR_BY_PACKAGE = {
    "core": "control",
    "uas": "uas",
    "memory": "memory",
    "domains": "domain",
    "conductor": "conductor",
    "chat": "conductor",
    "web": "web",
}

NODE_WIDTH = 156
NODE_HEIGHT = 34
COLUMN_GAP = 214
ROW_GAP = 46
MARGIN_X = 18
MARGIN_Y = 26

# Vertical trunk lanes in the gutter between two columns.
TRUNK_LANES = 5
TRUNK_PITCH = 8
TRUNK_INSET = 9


def _package_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _module_name(path: str, root: str) -> str:
    relative = os.path.relpath(path, root).replace(os.sep, ".")
    return relative[: -len(".py")]


def _resolve(target: str) -> Optional[str]:
    """Map an imported dotted path onto a module in this package, if it is one."""
    if not target.startswith(f"{PACKAGE}."):
        return None
    return target[len(PACKAGE) + 1:]


def _first_docstring_line(tree: ast.Module) -> str:
    """The module docstring's opening sentence, or "" when the module has none.

    This is what a node on the circuit says about itself. Taking it from the source the graph is
    already built from is the point: a hand-written label beside a generated diagram drifts the
    moment a module changes, and nobody notices.
    """
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    # Docstrings here open with one summary line, then a blank line and the detail.
    first = doc.strip().split('\n\n')[0]
    return " ".join(first.split())


def collect_graph(
    root: Optional[str] = None
) -> Tuple[List[str], Set[Tuple[str, str]], Dict[str, str]]:
    """Parse every module in the package and return its modules, internal import edges and the
    first line of each module's docstring."""
    root = root or _package_root()
    modules: List[str] = []
    raw_edges: Set[Tuple[str, str]] = set()
    source_by_module: Dict[str, str] = {}
    summaries: Dict[str, str] = {}

    for folder, _, files in os.walk(root):
        if "__pycache__" in folder:
            continue
        for filename in sorted(files):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            path = os.path.join(folder, filename)
            name = _module_name(path, root)
            modules.append(name)
            source_by_module[name] = path

    known = set(modules)

    for name in modules:
        try:
            with open(source_by_module[name], "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
        except (OSError, SyntaxError):
            continue

        summaries[name] = _first_docstring_line(tree)

        for node in ast.walk(tree):
            targets: List[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                targets.append(node.module)
                # `from sentinel_fleet.core import gateway` imports a module, not a symbol.
                for alias in node.names:
                    targets.append(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)

            for target in targets:
                resolved = _resolve(target)
                if resolved and resolved in known and resolved != name:
                    raw_edges.add((name, resolved))

    return sorted(modules), raw_edges, summaries


def _depths(modules: List[str], edges: Set[Tuple[str, str]]) -> Dict[str, int]:
    """Longest import chain below each module. Import cycles are cut rather than followed."""
    outgoing: Dict[str, List[str]] = {m: [] for m in modules}
    for source, target in edges:
        outgoing[source].append(target)

    depth: Dict[str, int] = {}
    visiting: Set[str] = set()

    def walk(module: str) -> int:
        if module in depth:
            return depth[module]
        if module in visiting:
            return 0  # cycle: stop descending instead of recursing forever
        visiting.add(module)
        below = [walk(target) for target in outgoing[module]]
        visiting.discard(module)
        depth[module] = 1 + max(below) if below else 0
        return depth[module]

    for module in modules:
        walk(module)
    return depth


def build_circuit(root: Optional[str] = None) -> Dict[str, object]:
    """Lay the graph out in dependency columns and return SVG-ready geometry."""
    modules, edges, summaries = collect_graph(root)
    depth = _depths(modules, edges)
    max_depth = max(depth.values()) if depth else 0

    # Importers sit left of what they import: column = how much of the stack is below you.
    columns: Dict[int, List[str]] = {}
    for module in modules:
        column = max_depth - depth[module]
        columns.setdefault(column, []).append(module)

    # Two packages both define a `models` module, so a bare basename would label them alike.
    basenames: Dict[str, int] = {}
    for module in modules:
        basenames[module.split(".")[-1]] = basenames.get(module.split(".")[-1], 0) + 1

    tallest = max((len(m) for m in columns.values()), default=1)
    nodes: Dict[str, Dict[str, object]] = {}
    for column, members in columns.items():
        members.sort(key=lambda m: (PILLAR_BY_PACKAGE.get(m.split(".")[0], "web"), m))
        # Centre every column on a shared midline; a column of one otherwise floats at the top.
        offset = (tallest - len(members)) * ROW_GAP / 2
        for row, module in enumerate(members):
            parts = module.split(".")
            package = parts[0]
            label = parts[-1] if basenames[parts[-1]] == 1 else ".".join(parts[-2:])
            nodes[module] = {
                "id": module,
                "label": label,
                "package": package,
                "pillar": PILLAR_BY_PACKAGE.get(package, "web"),
                "column": column,
                "x": MARGIN_X + column * COLUMN_GAP,
                "y": MARGIN_Y + offset + row * ROW_GAP,
                "width": NODE_WIDTH,
                "height": NODE_HEIGHT,
                "summary": summaries.get(module, ""),
                "imports": [],
                "imported_by": [],
            }

    # Every edge leaving a module turns down the same vertical trunk, and neighbouring modules
    # get different trunks. Without that, parallel runs sit on top of each other and the eye
    # cannot tell which trace belongs to which module.
    trunk_lane = {module: index % TRUNK_LANES for index, module in enumerate(sorted(nodes))}

    wires = []
    for source, target in sorted(edges):
        a, b = nodes[source], nodes[target]
        a["imports"].append(target)
        b["imported_by"].append(source)

        start_x = a["x"] + NODE_WIDTH
        start_y = a["y"] + NODE_HEIGHT / 2
        end_x = b["x"]
        end_y = b["y"] + NODE_HEIGHT / 2

        if end_x > start_x:
            # Orthogonal elbow: out to the trunk, down or up, then in. Traces, not curves.
            elbow = start_x + TRUNK_INSET + trunk_lane[source] * TRUNK_PITCH
            elbow = min(elbow, end_x - TRUNK_INSET)
            elbow = max(elbow, start_x + 6)
            path = f"M {start_x} {start_y} H {elbow} V {end_y} H {end_x}"
        else:
            # Only reachable if an import cycle collapses two modules into one column.
            detour = max(a["y"], b["y"]) + NODE_HEIGHT + 12
            path = (
                f"M {start_x} {start_y} H {start_x + 14} V {detour} "
                f"H {end_x - 14} V {end_y} H {end_x}"
            )

        wires.append({"source": source, "target": target, "path": path})

    height = MARGIN_Y * 2 + tallest * ROW_GAP
    width = MARGIN_X * 2 + (max_depth + 1) * COLUMN_GAP

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (n["column"], n["y"])),
        "wires": wires,
        "width": width,
        "height": height,
        "module_count": len(nodes),
        "wire_count": len(wires),
        # Named rather than counted: a module with no docstring gets no explanation on the
        # diagram, and the only way that gets fixed is if someone can see which ones they are.
        "undocumented": sorted(m for m, n in nodes.items() if not n["summary"]),
    }
