"""Static normal-package import graph; never imports an audited package."""

def module_name(path):
    stem = path[:-3]
    if stem.startswith('src/'):
        stem = stem[4:]
    if stem.endswith('/__init__'):
        stem = stem[:-9]
    return stem.replace('/', '.')

def build_graph(parsed):
    modules = {module_name(path): path for path in parsed}
    packages = {name: path for name, path in modules.items() if path.endswith('/__init__.py')}
    namespace_packages = {'.'.join(name.split('.')[:length])
                          for name in modules for length in range(1, len(name.split('.')))
                          if '.'.join(name.split('.')[:length]) not in modules}

    def initializers(module):
        parts = module.split('.')
        return {packages[prefix] for length in range(1, len(parts) + 1)
                if (prefix := '.'.join(parts[:length])) in packages}

    graph, external, dynamic, initialization_edges, namespaces = {}, {}, {}, {}, {}
    for path, facts in parsed.items():
        name_parts = module_name(path).split('.')
        package = name_parts if path.endswith('/__init__.py') else name_parts[:-1]
        targets, outside = set(), set()
        initialization = initializers(module_name(path)) - {path}
        namespace_segments = {prefix for length in range(1, len(name_parts))
                              if (prefix := '.'.join(name_parts[:length])) in namespace_packages}
        for item in facts['imports']:
            module = item['module']
            if item['level']:
                base = package[:len(package) - item['level'] + 1]
                module = '.'.join(base + ([module] if module else []))
            candidates = [module] + [module + '.' + name for name in item.get('names', []) if name != '*']
            found = [modules[candidate] for candidate in candidates if candidate in modules]
            targets.update(found)
            # Initializers also run for an imported namespace descendant or
            # a missing child of a known regular package before failure.
            for candidate in candidates:
                initialization.update(initializers(candidate) - {path})
                parts = candidate.split('.')
                namespace_segments.update(prefix for length in range(1, len(parts) + 1)
                                          if (prefix := '.'.join(parts[:length])) in namespace_packages)
            if not found and module not in namespace_packages:
                outside.add(module or '<unresolved-relative-import>')
        graph[path] = targets | initialization
        external[path] = outside
        dynamic[path] = facts['dynamic_dependency_sites']
        initialization_edges[path] = initialization
        namespaces[path] = namespace_segments
    return graph, external, dynamic, initialization_edges, namespaces

def closure(graph, start):
    visited, pending = set(), [start]
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        pending.extend(graph[path] - visited)
    return sorted(visited)

def verify(matrix):
    import sys

    checked = 0
    for source in matrix['sources']:
        rows = [row for row in matrix['rows'] if row['source'] == source and row['kind'] == 'python-module']
        parsed = {row['path']: row for row in rows}
        graph, external, dynamic, initializers, namespaces = build_graph(parsed)
        modules = {module_name(path): path for path in parsed}
        for row in rows:
            path = row['path']
            transitive = closure(graph, path)
            expected = row['dependencies']
            outside = sorted(set().union(*(external[p] for p in transitive)))
            assert expected['internal_static_closure'] == transitive, path
            assert expected['stdlib'] == [p for p in outside if p.split('.')[0] in sys.stdlib_module_names], path
            assert expected['external_or_unresolved'] == [p for p in outside if p.split('.')[0] not in sys.stdlib_module_names], path
            assert expected['dynamic_sites'] == {p: dynamic[p] for p in transitive if dynamic[p]}, path
            assert not expected['runtime_dependency_closure_proven'], path
            for target in graph[path] | {path}:
                parts = module_name(target).split('.')
                for length in range(1, len(parts)):
                    parent = modules.get('.'.join(parts[:length]))
                    if parent and parent.endswith('/__init__.py'):
                        assert parent in transitive, (path, target, parent)
            checked += 1

    def deps(source, suffix):
        return next(row['dependencies'] for row in matrix['rows']
                    if row['source'] == source and row['path'].endswith(suffix))
    s3 = deps('Roshambo', '/aws/s3.py')
    assert {'src/roshambo/__init__.py', 'src/roshambo/aws/__init__.py'} <= set(s3['internal_static_closure'])
    assert {'psycopg', 'boto3'} <= set(s3['external_or_unresolved'])
    folder = deps('FolderHome', '/application/administrative_drafts.py')
    assert {'src/folderhome/application/__init__.py', 'src/folderhome/contracts/__init__.py'} <= set(folder['internal_static_closure'])
    nemo = deps('NemoFold', '/action_journal.py')
    assert {'src/nemofold/__init__.py', 'src/nemofold/contracts.py'} <= set(nemo['internal_static_closure'])

    synthetic = {
        'entry.py': dict(imports=[dict(module='pkg.sub.mod', level=0, line=1)], dynamic_dependency_sites=[]),
        'pkg/__init__.py': dict(imports=[dict(module='entry', level=0, line=1), dict(module='psycopg', level=0, line=2)], dynamic_dependency_sites=[]),
        'pkg/sub/mod.py': dict(imports=[], dynamic_dependency_sites=[]),
    }
    graph, external, dynamic, initializers, namespaces = build_graph(synthetic)
    assert closure(graph, 'entry.py') == ['entry.py', 'pkg/__init__.py', 'pkg/sub/mod.py']
    assert external['pkg/__init__.py'] == {'psycopg'}
    assert 'pkg.sub' in namespaces['entry.py']
    assert 'pkg/sub/__init__.py' not in graph
    assert checked == 344
    print(f'Verified {checked} derived closures, three source examples, target initializer, cycle and namespace controls')

if __name__ == '__main__':
    import json
    from pathlib import Path

    matrix_path = Path(__file__).resolve().parents[2] / 'system/imported_capabilities/FEATURE-COMPARISON.json'
    verify(json.loads(matrix_path.read_text(encoding='utf-8')))
