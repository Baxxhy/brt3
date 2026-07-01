"""Extract a conservative mutation scaffold around one precise seed test."""

from __future__ import annotations

import ast
import copy
import hashlib
import re
import textwrap
from pathlib import Path
from typing import Any

from core.io_utils import read_repo_file
from core.schema import HostContext, HostScaffold, ProtocolRecovery, RetrievedTest


_SETUP_NAMES = {
    "setUp",
    "setUpClass",
    "setup_method",
    "setup_class",
}
_TEARDOWN_NAMES = {
    "tearDown",
    "tearDownClass",
    "teardown_method",
    "teardown_class",
}


def extract_host_scaffold(
    instance_id: str,
    precise_seed: dict[str, Any],
    related_test: RetrievedTest | None,
    host: HostContext,
    buggy_worktree: str,
) -> HostScaffold:
    test_file = str(
        precise_seed.get("test_file")
        or (related_test.file if related_test else "")
        or host.host_file
    )
    test_entry = str(
        precise_seed.get("test_entry")
        or (related_test.name if related_test else "")
        or host.seed_test_name
    )
    enclosing_class = str(
        precise_seed.get("enclosing_class") or host.host_class or ""
    )
    test_name = str(
        precise_seed.get("test_name")
        or host.seed_test_name
        or _last_entry_segment(test_entry)
    )
    source = read_repo_file(buggy_worktree, test_file) if test_file else ""
    if not source:
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            "full test file not found in buggy worktree",
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            f"full test file AST parse failed: {exc}",
        )

    seed_node, class_node = _find_seed(
        tree,
        test_entry,
        test_name,
        enclosing_class,
    )
    if seed_node is None:
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            "precise seed function could not be located in full test file",
        )

    seed_code = _node_source(source, seed_node, include_decorators=True)
    if not seed_code:
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            "precise seed function source span is empty",
        )

    imports = [
        _node_source(source, node)
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imports = [item for item in imports if item]
    pytestmark_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and "pytestmark" in _assigned_names(node)
    ]
    pytestmark = "\n".join(
        item
        for item in (_node_source(source, node) for node in pytestmark_nodes)
        if item
    )

    fixture_args = [
        arg.arg
        for arg in seed_node.args.posonlyargs
        + seed_node.args.args
        + seed_node.args.kwonlyargs
        if arg.arg not in {"self", "cls"}
    ]
    class_attributes: list[ast.AST] = []
    setup_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    teardown_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    class_helper_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    class_wrapper = ""
    class_decorators: list[str] = []
    class_bases: list[str] = []
    if class_node is not None:
        class_wrapper = _definition_header(source, class_node)
        class_decorators = [
            _expression_source(source, item)
            for item in class_node.decorator_list
            if _expression_source(source, item)
        ]
        class_bases = [
            _expression_source(source, item)
            for item in class_node.bases
            if _expression_source(source, item)
        ]
        class_attributes = [
            child
            for child in class_node.body
            if isinstance(child, (ast.Assign, ast.AnnAssign))
        ]
        setup_nodes = [
            child
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name in _SETUP_NAMES
        ]
        teardown_nodes = [
            child
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name in _TEARDOWN_NAMES
        ]
        referenced_methods = _self_attributes(seed_node)
        class_helper_nodes = [
            child
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name in referenced_methods
            and child is not seed_node
            and child.name not in _SETUP_NAMES | _TEARDOWN_NAMES
        ]

    dependency_roots: list[ast.AST] = [
        seed_node,
        *class_attributes,
        *setup_nodes,
        *teardown_nodes,
        *class_helper_nodes,
    ]
    references: set[str] = set(fixture_args)
    for node in dependency_roots:
        references.update(_loaded_names(node))
    if class_node is not None:
        for node in [*class_node.bases, *class_node.decorator_list]:
            references.update(_loaded_names(node))

    definitions = _module_definitions(tree)
    definitions = {
        name: node
        for name, node in definitions.items()
        if node is not seed_node and node is not class_node
    }
    selected_module_nodes: list[ast.AST] = []
    selected_ids: set[int] = set()
    for _ in range(4):
        added = False
        for name in sorted(references):
            node = definitions.get(name)
            if node is None or id(node) in selected_ids:
                continue
            selected_ids.add(id(node))
            selected_module_nodes.append(node)
            references.update(_loaded_names(node))
            added = True
        if not added:
            break

    dependency_evidence = [
        *imports,
        pytestmark,
        class_wrapper,
        *[_node_source(source, node) for node in class_attributes],
        *[_node_source(source, node, include_decorators=True) for node in setup_nodes],
        *[_node_source(source, node, include_decorators=True) for node in teardown_nodes],
        *[_node_source(source, node, include_decorators=True) for node in class_helper_nodes],
        *[_node_source(source, node, include_decorators=True) for node in selected_module_nodes],
    ]
    if not any(item.strip() for item in dependency_evidence):
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            "AST dependency closure is empty",
        )

    local_helpers = _helper_records(
        source,
        [*selected_module_nodes, *class_helper_nodes],
    )
    scaffold_code = _assemble_scaffold(
        source=source,
        imports=imports,
        pytestmark=pytestmark,
        module_nodes=selected_module_nodes,
        class_node=class_node,
        class_wrapper=class_wrapper,
        class_body_nodes=[
            *class_attributes,
            *setup_nodes,
            *teardown_nodes,
            *class_helper_nodes,
            seed_node,
        ],
        seed_node=seed_node,
        seed_code=seed_code,
    )
    try:
        ast.parse(scaffold_code)
    except SyntaxError as exc:
        return _fallback_scaffold(
            instance_id,
            host,
            test_file,
            test_entry,
            f"assembled HostScaffold is not valid Python: {exc}",
        )
    framework = _framework(source, class_node)
    seed_hash = _sha256(seed_code)
    return HostScaffold(
        instance_id=instance_id,
        host_scaffold_mode="ast_scaffold",
        test_file=test_file,
        test_entry=(
            f"{class_node.name}.{seed_node.name}" if class_node else seed_node.name
        ),
        enclosing_class=class_node.name if class_node else "",
        framework=framework,
        cleaned_imports=imports,
        module_pytestmark=pytestmark,
        class_wrapper=class_wrapper,
        setup_methods=[
            _node_source(source, node, include_decorators=True)
            for node in setup_nodes
        ],
        teardown_methods=[
            _node_source(source, node, include_decorators=True)
            for node in teardown_nodes
        ],
        fixture_args=fixture_args,
        local_helpers=local_helpers,
        seed_decorators=[
            _expression_source(source, item)
            for item in seed_node.decorator_list
            if _expression_source(source, item)
        ],
        seed_function_signature=_function_signature(seed_node),
        seed_function_body=_function_body(source, seed_node),
        seed_function_code=seed_code,
        class_decorators=class_decorators,
        class_bases=class_bases,
        class_attributes=[
            _node_source(source, node) for node in class_attributes
        ],
        scaffold_code=scaffold_code,
        scaffold_hash=_sha256(scaffold_code),
        seed_function_hash=seed_hash,
    )


def apply_scaffold_to_protocol(
    protocol: ProtocolRecovery,
    scaffold: HostScaffold,
) -> ProtocolRecovery:
    if scaffold.host_scaffold_mode != "ast_scaffold":
        protocol.protocol_risks.append(
            f"HostScaffold fallback retained old protocol: {scaffold.fallback_reason}"
        )
        return protocol
    protocol.test_file = scaffold.test_file or protocol.test_file
    protocol.test_framework = scaffold.framework or protocol.test_framework
    protocol.imports = list(scaffold.cleaned_imports)
    protocol.fixtures = list(scaffold.fixture_args)
    protocol.pytest_marks = (
        [scaffold.module_pytestmark] if scaffold.module_pytestmark else []
    )
    protocol.decorators = list(scaffold.seed_decorators)
    class_context = "\n".join(
        [
            scaffold.class_wrapper,
            *[
                textwrap.indent(item, "    ")
                for item in scaffold.class_attributes
            ],
        ]
    ).strip()
    protocol.class_context = class_context
    protocol.setup_methods = list(scaffold.setup_methods)
    protocol.teardown_methods = list(scaffold.teardown_methods)
    protocol.local_helpers = [
        {
            "name": str(item.get("name") or ""),
            "file": scaffold.test_file,
            "code": str(item.get("code") or ""),
        }
        for item in scaffold.local_helpers
    ]
    protocol.selected_seed_name = scaffold.test_entry
    return protocol


def fallback_host_scaffold(
    instance_id: str,
    host: HostContext,
    test_file: str,
    test_entry: str,
    reason: str,
) -> HostScaffold:
    return _fallback_scaffold(
        instance_id,
        host,
        test_file,
        test_entry,
        reason,
    )


def _fallback_scaffold(
    instance_id: str,
    host: HostContext,
    test_file: str,
    test_entry: str,
    reason: str,
) -> HostScaffold:
    pieces = [
        host.imports,
        host.pytestmark,
        host.setup_context,
        host.seed_test_code,
    ]
    scaffold_code = "\n\n".join(
        item.strip() for item in pieces if item and item.strip()
    )
    seed_code = host.seed_test_code or ""
    return HostScaffold(
        instance_id=instance_id,
        host_scaffold_mode="fallback_old",
        test_file=test_file or host.host_file,
        test_entry=test_entry or host.seed_test_name,
        enclosing_class=host.host_class,
        framework="unknown",
        cleaned_imports=[
            line
            for line in host.imports.splitlines()
            if line.startswith(("import ", "from "))
        ],
        module_pytestmark=host.pytestmark,
        class_wrapper=host.setup_context,
        setup_methods=[host.setup_context] if host.setup_context else [],
        fixture_args=list(host.fixtures),
        seed_decorators=list(host.decorators),
        seed_function_code=seed_code,
        scaffold_code=scaffold_code,
        scaffold_hash=_sha256(scaffold_code),
        seed_function_hash=_sha256(seed_code),
        fallback_reason=reason,
    )


def _find_seed(
    tree: ast.Module,
    test_entry: str,
    test_name: str,
    enclosing_class: str,
) -> tuple[
    ast.FunctionDef | ast.AsyncFunctionDef | None,
    ast.ClassDef | None,
]:
    normalized = test_entry.replace("::", ".")
    parts = [item for item in normalized.split(".") if item]
    wanted_name = test_name or (parts[-1] if parts else "")
    wanted_class = enclosing_class or (parts[-2] if len(parts) >= 2 else "")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if wanted_class and node.name != wanted_class:
                continue
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == wanted_name
                ):
                    return child, node
        elif (
            not wanted_class
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == wanted_name
        ):
            return node, None
    return None, None


def _module_definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _assigned_names(node):
                if name != "pytestmark":
                    definitions[name] = node
    return definitions


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: set[str] = set()
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                names.add(child.id)
    return names


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _self_attributes(node: ast.AST) -> set[str]:
    return {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Name)
        and child.value.id in {"self", "cls"}
    }


def _helper_records(source: str, nodes: list[ast.AST]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[int] = set()
    for node in sorted(nodes, key=lambda item: getattr(item, "lineno", 0)):
        if id(node) in seen:
            continue
        seen.add(id(node))
        names = (
            [node.name]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            else sorted(_assigned_names(node))
        )
        code = _node_source(
            source,
            node,
            include_decorators=isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ),
        )
        records.append(
            {
                "name": ",".join(names),
                "kind": type(node).__name__,
                "code": code,
            }
        )
    return records


def _assemble_scaffold(
    source: str,
    imports: list[str],
    pytestmark: str,
    module_nodes: list[ast.AST],
    class_node: ast.ClassDef | None,
    class_wrapper: str,
    class_body_nodes: list[ast.AST],
    seed_node: ast.FunctionDef | ast.AsyncFunctionDef,
    seed_code: str,
) -> str:
    module_pieces = [*imports]
    if pytestmark:
        module_pieces.append(pytestmark)
    for node in sorted(
        {id(item): item for item in module_nodes}.values(),
        key=lambda item: getattr(item, "lineno", 0),
    ):
        module_pieces.append(
            _node_source(
                source,
                node,
                include_decorators=isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ),
            )
        )
    if class_node is None:
        module_pieces.append(seed_code)
    else:
        body_pieces: list[str] = []
        for node in sorted(
            {id(item): item for item in class_body_nodes}.values(),
            key=lambda item: getattr(item, "lineno", 0),
        ):
            body_pieces.append(
                _node_source(
                    source,
                    node,
                    include_decorators=isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ),
                )
            )
        class_code = class_wrapper.rstrip() + "\n"
        class_code += textwrap.indent(
            "\n\n".join(item for item in body_pieces if item).strip() or "pass",
            "    ",
        )
        module_pieces.append(class_code)
    return "\n\n".join(item.strip() for item in module_pieces if item.strip()) + "\n"


def _node_source(
    source: str,
    node: ast.AST,
    include_decorators: bool = False,
) -> str:
    lines = source.splitlines()
    start = int(getattr(node, "lineno", 1))
    if include_decorators:
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start = min(start, *(int(item.lineno) for item in decorators))
    end = int(getattr(node, "end_lineno", start))
    return textwrap.dedent("\n".join(lines[start - 1 : end])).strip()


def _expression_source(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or ast.unparse(node)).strip()


def _definition_header(source: str, node: ast.ClassDef) -> str:
    lines = source.splitlines()
    start = int(node.lineno)
    if node.decorator_list:
        start = min(start, *(int(item.lineno) for item in node.decorator_list))
    first_body_line = (
        int(node.body[0].lineno) if node.body else int(node.end_lineno or node.lineno) + 1
    )
    header = "\n".join(lines[start - 1 : max(start, first_body_line - 1)])
    return textwrap.dedent(header).strip()


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    clone = copy.deepcopy(node)
    clone.decorator_list = []
    clone.body = [ast.Pass()]
    ast.fix_missing_locations(clone)
    rendered = ast.unparse(clone)
    return rendered.rsplit("\n", 1)[0].strip()


def _function_body(
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    if not node.body:
        return ""
    lines = source.splitlines()
    start = int(node.body[0].lineno)
    end = int(node.body[-1].end_lineno or node.body[-1].lineno)
    return textwrap.dedent("\n".join(lines[start - 1 : end])).strip()


def _framework(source: str, cls: ast.ClassDef | None) -> str:
    bases = " ".join(ast.unparse(base) for base in cls.bases) if cls else ""
    if (
        "django.test" in source
        or re.search(
            r"\b(?:TestCase|TransactionTestCase|SimpleTestCase|LiveServerTestCase)\b",
            bases,
        )
    ):
        return "django"
    if "unittest" in source or "TestCase" in bases:
        return "unittest"
    if "pytest" in source or re.search(r"\bpytestmark\b", source):
        return "pytest"
    return "pytest" if "def test" in source else "unknown"


def _last_entry_segment(entry: str) -> str:
    return entry.replace("::", ".").rsplit(".", 1)[-1]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""
