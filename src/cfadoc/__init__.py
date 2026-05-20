from __future__ import annotations

import json
import re
import subprocess
import tomllib
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

import questionary as Q
import yaml
from rich.console import Console
from rich.panel import Panel

console = Console()
LEGACY_DOCS_DEPS = {"mkdocs", "mkdocs-material", "mkdocstrings"}


def _ask(question):
    answer = question.ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


def _run(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, f"Command not found: {command[0]}"
    except subprocess.CalledProcessError as err:
        details = err.stderr.strip() or err.stdout.strip() or str(err)
        return False, details
    return True, (result.stdout.strip() or result.stderr.strip())


def _load_template(name: str) -> str:
    template_path = resources.files("cfadoc.templates").joinpath(name)
    return template_path.read_text(encoding="utf-8")


def _render_template(template_name: str, values: dict[str, str]) -> str:
    content = _load_template(template_name)
    for key, value in values.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except Exception:
        return {}


def _normalize_repo_url(remote: str) -> str | None:
    remote = remote.strip()
    if not remote:
        return None
    if remote.startswith("git@") and ":" in remote:
        host, path = remote.split(":", 1)
        host = host.split("@", 1)[1]
        path = path.removesuffix(".git")
        return f"https://{host}/{path}"
    if remote.startswith(("https://", "http://")):
        return remote.removesuffix(".git")
    return None


def _github_site_url(repo_url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(repo_url)
    if parsed.netloc.lower() != "github.com":
        return None, None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None, None
    owner, repo_name = parts[0], parts[1]
    return repo_name, f"https://{owner}.github.io/{repo_name}"


def _dep_base_name(spec: str) -> str:
    cleaned = spec.split(";", 1)[0].strip()
    cleaned = re.split(r"[<>=!~ ]", cleaned, maxsplit=1)[0]
    cleaned = cleaned.split("[", 1)[0]
    return cleaned.lower()


def _collect_dependency_names(pyproject_data: dict) -> set[str]:
    names: set[str] = set()
    project = pyproject_data.get("project", {})
    for dep in project.get("dependencies", []):
        names.add(_dep_base_name(dep))
    groups = pyproject_data.get("dependency-groups", {})
    for entries in groups.values():
        for dep in entries:
            names.add(_dep_base_name(dep))
    return names


def _dependency_locations(pyproject_data: dict) -> dict[str, set[str | None]]:
    """Map dependency name to where it is declared.

    Uses None for main project.dependencies, and group name for dependency-groups.
    """
    locations: dict[str, set[str | None]] = {}

    project = pyproject_data.get("project", {})
    for dep in project.get("dependencies", []):
        name = _dep_base_name(dep)
        locations.setdefault(name, set()).add(None)

    groups = pyproject_data.get("dependency-groups", {})
    for group_name, entries in groups.items():
        for dep in entries:
            name = _dep_base_name(dep)
            locations.setdefault(name, set()).add(group_name)

    return locations


def _dependency_specs_by_location(
    pyproject_data: dict,
) -> dict[str, list[tuple[str | None, str]]]:
    """Map dependency name to raw spec strings by location."""
    specs: dict[str, list[tuple[str | None, str]]] = {}

    project = pyproject_data.get("project", {})
    for dep in project.get("dependencies", []):
        name = _dep_base_name(dep)
        specs.setdefault(name, []).append((None, dep))

    groups = pyproject_data.get("dependency-groups", {})
    for group_name, entries in groups.items():
        for dep in entries:
            name = _dep_base_name(dep)
            specs.setdefault(name, []).append((group_name, dep))

    return specs


def _confirm_or_edit(label: str, detected: str | None, default_fallback: str) -> str:
    return _ask(Q.text(f"Enter {label}:", default=detected or default_fallback))


def _write_file(path: Path, content: str, allow_overwrite: bool = True) -> bool:
    if path.exists() and not allow_overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _ensure_docs_index(project_display_name: str) -> None:
    index_path = Path("docs/index.md")
    if index_path.exists():
        console.print("[green]OK[/] docs/index.md already exists")
        return

    create = _ask(Q.confirm("docs/index.md is missing. Create it now?", default=True))
    if not create:
        console.print("[yellow]Skipped[/] docs/index.md creation")
        return

    default_content = _render_template(
        "index.md",
        {"project_display_name": project_display_name},
    )
    _write_file(index_path, default_content)
    console.print("[green]Created[/] docs/index.md")


def _ensure_zensical_toml() -> None:
    pyproject_data = _read_toml(Path("pyproject.toml"))
    project_name = pyproject_data.get("project", {}).get("name")

    ok, git_remote = _run(["git", "config", "--get", "remote.origin.url"])
    repo_url_guess = _normalize_repo_url(git_remote) if ok else None
    repo_name_guess, site_url_guess = (
        _github_site_url(repo_url_guess) if repo_url_guess else (None, None)
    )

    repo_name_default = repo_name_guess or Path.cwd().name
    site_name = _confirm_or_edit("site name", project_name, Path.cwd().name)
    repo_url = _confirm_or_edit(
        "repository URL",
        repo_url_guess,
        f"https://github.com/ORG/{repo_name_default}",
    )
    repo_name = _confirm_or_edit("repository name", repo_name_guess, repo_name_default)
    site_url = _confirm_or_edit(
        "site URL",
        site_url_guess,
        f"https://ORG.github.io/{repo_name}",
    )

    python_path_default = "src" if Path("src").exists() else "."
    python_path = _ask(
        Q.text(
            "Path to Python package root for mkdocstrings:",
            default=python_path_default,
        )
    )

    # if mkdocs.yaml exists, copy nav from that
    if mkdocs_yaml := _find_mkdocs_yaml():
        with open(mkdocs_yaml) as f:
            content = yaml.load(f, Loader=yaml.BaseLoader)

        assert "nav" in content
        nav_paths = content["nav"]
    # otherwise, list the files in docs/
    else:
        # remove the docs/ prefix
        nav_paths = [Path(*p.parts[1:]) for p in Path("docs").glob("*.md")]
        # ensure that index.md comes first
        first = Path("index.md")
        assert first in nav_paths
        nav_paths.insert(0, nav_paths.pop(nav_paths.index(first)))

    nav = json.dumps(nav_paths)

    content = _render_template(
        "zensical.toml",
        {
            "site_name": site_name,
            "site_url": site_url,
            "repo_url": repo_url,
            "repo_name": repo_name,
            "python_path": python_path,
            "nav": nav,
        },
    )

    target = Path("zensical.toml")
    if target.exists():
        overwrite = _ask(
            Q.confirm(
                "zensical.toml exists. Overwrite with updated config?",
                default=False,
            )
        )
        if not overwrite:
            console.print("[yellow]Skipped[/] zensical.toml")
            return

    _write_file(target, content)
    console.print("[green]Wrote[/] zensical.toml")


def _ensure_docs_workflow() -> None:
    workflow_path = Path(".github/workflows/docs.yaml")
    if workflow_path.exists():
        overwrite = _ask(
            Q.confirm(
                ".github/workflows/docs.yaml exists. Replace it with zensical workflow?",
                default=False,
            )
        )
        if not overwrite:
            console.print("[yellow]Skipped[/] docs workflow update")
            return

    _write_file(workflow_path, _load_template("docs.yaml"))
    console.print("[green]Wrote[/] .github/workflows/docs.yaml")


def _find_mkdocs_yaml() -> Path | None:
    paths = [Path(x) for x in ["mkdocs.yaml", "mkdocs.yml"] if Path(x).exists()]
    if len(paths) == 0:
        return None
    if len(paths) == 1:
        return paths[0]
    else:
        raise RuntimeError("Multiple mkdocs yaml's detected")


def _cleanup_mkdocs_files() -> None:
    if mkdocs_yaml := _find_mkdocs_yaml():
        if _ask(Q.confirm(f"Remove {mkdocs_yaml}?", default=True)):
            mkdocs_yaml.unlink()
            console.print(f"[green]Removed[/] {mkdocs_yaml}")

    docs_js = Path("docs/javascript")
    if docs_js.exists() and _ask(
        Q.confirm("Delete docs/javascript directory?", default=False)
    ):
        for entry in sorted(docs_js.rglob("*"), reverse=True):
            if entry.is_file():
                entry.unlink()
            elif entry.is_dir():
                entry.rmdir()
        docs_js.rmdir()
        console.print("[green]Removed[/] docs/javascript")


def _find_legacy_mkdocs_workflows() -> list[Path]:
    workflows_dir = Path(".github/workflows")
    if not workflows_dir.exists():
        return []

    legacy_files: list[Path] = []
    for workflow_path in sorted(workflows_dir.glob("*.y*ml")):
        try:
            content = workflow_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "mkdocs" in content.lower():
            legacy_files.append(workflow_path)

    return legacy_files


def _cleanup_legacy_mkdocs_workflows() -> None:
    legacy_workflows = _find_legacy_mkdocs_workflows()
    if not legacy_workflows:
        return

    selected = _ask(
        Q.checkbox(
            "Select legacy mkdocs workflow files to remove:",
            choices=[
                Q.Choice(str(path), value=path, checked=True)
                for path in legacy_workflows
            ],
        )
    )

    for workflow_path in selected:
        try:
            workflow_path.unlink()
            console.print(f"[green]Removed[/] {workflow_path}")
        except Exception as err:
            console.print(f"[red]Failed[/] removing {workflow_path}: {err}")


def _readme_mentions_mkdocs() -> bool:
    readme_path = Path("README.md")
    if not readme_path.exists():
        return False
    try:
        content = readme_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return "mkdocs" in content.lower()


def _ensure_api_stub(package_name: str) -> None:
    api_md = Path("docs/api.md")
    if api_md.exists():
        return
    if not _ask(
        Q.confirm("docs/api.md is missing. Create API reference page?", default=True)
    ):
        return
    _write_file(
        api_md,
        _render_template("api.md", {"package_name": package_name}),
    )
    console.print("[green]Created[/] docs/api.md")


def _update_gitignore() -> None:
    gitignore_path = Path(".gitignore")
    lines: list[str] = []
    if gitignore_path.exists():
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()

    docs_ignore_patterns = {"docs", "docs/", "/docs", "/docs/"}
    filtered = [line for line in lines if line.strip() not in docs_ignore_patterns]
    if len(filtered) != len(lines):
        if _ask(
            Q.confirm(
                "Found docs ignore rules in .gitignore. Remove them?", default=True
            )
        ):
            lines = filtered
            console.print("[green]Updated[/] removed docs ignore rules")

    has_site = any(
        line.strip() in {"site", "site/", "/site", "/site/"} for line in lines
    )
    if not has_site:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append("site/")
        console.print("[green]Updated[/] added site/ to .gitignore")

    gitignore_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _run_dependency_updates(pyproject_data: dict) -> str:
    names = _collect_dependency_names(pyproject_data)
    dep_locations = _dependency_locations(pyproject_data)

    group = _ask(
        Q.text(
            "Dependency group for docs packages:",
            default="docs",
            validate=lambda value: (
                True if value.strip() else "Please enter a dependency group name."
            ),
        )
    ).strip()
    group_args = ["--group", group]

    legacy = sorted(LEGACY_DOCS_DEPS & names)
    if legacy:
        if _ask(
            Q.confirm(
                f"Detected legacy docs dependencies ({', '.join(legacy)}). Remove them?",
                default=True,
            )
        ):
            for dep in legacy:
                locations = dep_locations.get(dep, set())
                if not locations:
                    continue
                for location in sorted(locations, key=lambda x: "" if x is None else x):
                    command = ["uv", "remove"]
                    if location is not None:
                        command += ["--group", location]
                    command.append(dep)
                    ok, out = _run(command)
                    label = (
                        f"{dep} from group '{location}'"
                        if location is not None
                        else f"{dep} from main dependencies"
                    )
                    console.print(
                        f"[green]Removed[/] {label}"
                        if ok
                        else f"[red]Failed[/] {label}: {out}"
                    )

    docs_packages = ["zensical", "mdx-truly-sane-lists", "mkdocstrings-python"]
    spec_map = _dependency_specs_by_location(pyproject_data)
    relocations: list[tuple[str, str, str]] = []
    deps_in_target_group: set[str] = set()
    for dep in docs_packages:
        entries = spec_map.get(dep, [])
        if any(location == group for location, _ in entries):
            deps_in_target_group.add(dep)
        for location, spec in entries:
            if location is None or location == group:
                continue
            relocations.append((dep, location, spec))

    if relocations:
        selected_indexes = _ask(
            Q.checkbox(
                f"Select dependencies to move into group '{group}':",
                choices=[
                    Q.Choice(
                        title=f"{dep} (from '{location}')",
                        value=index,
                        checked=True,
                    )
                    for index, (dep, location, _spec) in enumerate(relocations)
                ],
            )
        )

        for index in selected_indexes:
            dep, location, spec = relocations[index]
            remove_ok, remove_out = _run(["uv", "remove", "--group", location, dep])
            if not remove_ok:
                console.print(
                    f"[red]Failed[/] removing {dep} from group '{location}': {remove_out}"
                )
                continue

            console.print(f"[green]Removed[/] {dep} from group '{location}'")

            if dep in deps_in_target_group:
                continue

            add_ok, add_out = _run(["uv", "add", "--group", group, spec])
            if add_ok:
                deps_in_target_group.add(dep)
                console.print(f"[green]Added[/] {spec} to group '{group}'")
            else:
                console.print(
                    f"[red]Failed[/] adding {spec} to group '{group}': {add_out}"
                )

    pyproject_data = _read_toml(Path("pyproject.toml"))
    names = _collect_dependency_names(pyproject_data)

    missing = [
        dep
        for dep in ["zensical", "mdx-truly-sane-lists", "mkdocstrings-python"]
        if dep not in names
    ]
    if missing:
        selected = _ask(
            Q.checkbox(
                "Select docs dependencies to add (space to toggle, enter to confirm):",
                choices=[
                    Q.Choice(dep, checked=True)
                    for dep in [
                        "zensical",
                        "mdx-truly-sane-lists",
                        "mkdocstrings-python",
                    ]
                    if dep in missing
                ],
            )
        )
        if selected:
            ok, out = _run(["uv", "add", *group_args, *selected])
            console.print(
                "[green]Done[/] uv add ..." if ok else f"[red]Failed[/] {out}"
            )
        else:
            console.print(
                "[yellow]Skipped[/] no docs dependencies selected for install"
            )

    return group


def _detect_package_name() -> str:
    pyproject_data = _read_toml(Path("pyproject.toml"))
    project_name = pyproject_data.get("project", {}).get("name", "")
    normalized = project_name.replace("-", "_") if project_name else ""

    src_dir = Path("src")
    if normalized and (src_dir / normalized / "__init__.py").exists():
        guess = normalized
    elif normalized:
        guess = normalized
    else:
        guess = Path.cwd().name.replace("-", "_")

    return _confirm_or_edit("Python package name", guess, guess)


def _validate_build(dependency_group: str | None = None) -> None:
    if not _ask(
        Q.confirm(
            "Run 'uv run zensical build --strict' to validate setup?", default=True
        )
    ):
        return

    command = ["uv", "run"]

    if dependency_group is not None:
        command += ["--group", dependency_group]

    command += ["zensical", "build", "--strict"]
    ok, out = _run(command)

    if ok:
        console.print("[green]Build succeeded[/]")
    else:
        console.print(f"[red]Build failed[/] {out}")


def _run_cli() -> None:
    console.print(
        Panel.fit(
            "Interactive setup for Zensical docs in a new or existing repository.",
            title="cfadoc setup",
            border_style="cyan",
        )
    )

    if not Path(".").resolve().joinpath(".git").exists():
        proceed = _ask(
            Q.confirm(
                "No .git directory detected in current folder. Continue anyway?",
                default=True,
            )
        )
        if not proceed:
            console.print("[yellow]Cancelled[/]")
            return

    package_name = _detect_package_name()
    pyproject_data = _read_toml(Path("pyproject.toml"))
    dep_names = _collect_dependency_names(pyproject_data)
    mkdocs_yaml = _find_mkdocs_yaml()
    has_docs_js = Path("docs/javascript").exists()
    legacy_deps = sorted(LEGACY_DOCS_DEPS & dep_names)
    legacy_workflows = _find_legacy_mkdocs_workflows()

    if mkdocs_yaml or has_docs_js or legacy_deps or legacy_workflows:
        detected: list[str] = []
        if mkdocs_yaml:
            detected.append(str(mkdocs_yaml))
        if has_docs_js:
            detected.append("docs/javascript")
        if legacy_deps:
            detected.append(f"legacy deps: {', '.join(legacy_deps)}")
        if legacy_workflows:
            detected.append(
                "legacy workflows: " + ", ".join(str(path) for path in legacy_workflows)
            )
        console.print(
            f"[cyan]Detected legacy mkdocs setup:[/] {'; '.join(detected)}. "
            "Will offer migration cleanups where relevant."
        )
    else:
        console.print(
            "[cyan]No mkdocs markers detected; continuing with standard setup.[/]"
        )

    _ensure_docs_index(project_display_name=package_name)
    _ensure_api_stub(package_name)
    _ensure_zensical_toml()
    _ensure_docs_workflow()
    _update_gitignore()

    _cleanup_mkdocs_files()
    _cleanup_legacy_mkdocs_workflows()
    dependency_group = _run_dependency_updates(pyproject_data)

    _validate_build(dependency_group)
    console.print("\n[bold green]Setup complete.[/bold green]")

    console.print("\n[bold]Manual follow-ups:[/bold]")
    console.print("- In GitHub repo settings, set Pages source to GitHub Actions")
    if _readme_mentions_mkdocs():
        console.print("- README.md mentions 'mkdocs'. Consider revising it.")


def cli() -> None:
    """Run the CLI"""
    try:
        _run_cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user.[/yellow]")
