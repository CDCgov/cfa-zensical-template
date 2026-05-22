from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import chevron
import questionary
import yaml
from rich.console import Console
from rich.panel import Panel


@dataclasses.dataclass
class Action:
    description: str
    fun: Callable[[], Any]


@dataclasses.dataclass
class Dependency:
    name: str
    group: str | None

    def __post_init__(self):
        self.name = self._basename(self.name)

    @staticmethod
    def _basename(x: str) -> str:
        out = x.split(";", 1)[0].strip()
        out = re.split(r"[<>=!~ ]", out, maxsplit=1)[0]
        out = out.split("[", 1)[0]
        out = out.lower()
        return out


class CLI:
    legacy_dep_names = ["mkdocs", "mkdocs-material", "mkdocstrings"]
    docs_dep_names = ["zensical", "mdx-truly-sane-lists", "mkdocstrings-python"]
    default_repo_owner = "cdcent"

    def __init__(self, console=Console()):
        self.console = console
        self.template_values = {}
        self.post_msgs = []

    def msg(self, *args):
        self.console.print(*args)

    def _text(self, msg: str, default: str | None) -> Any:
        try:
            return (
                questionary.text(
                    f"{msg}:", default=default or "", validate=lambda x: len(x) > 0
                )
                .unsafe_ask()
                .strip()
            )
        except KeyboardInterrupt:
            self.msg("[yellow]Cancelled[/]")
            sys.exit(0)

    @staticmethod
    def _run(command: list[str]) -> None | str:
        try:
            result = subprocess.run(command, check=True, text=True)

            return result.stdout.strip() or None
        except Exception:
            return None

    @staticmethod
    def _load_template(name: str) -> str:
        return (
            resources.files("cfadoc.templates")
            .joinpath(name)
            .read_text(encoding="utf-8")
        )

    @classmethod
    def _render_template(cls, name: str, values: dict[str, str]) -> str:
        template = cls._load_template(name)
        return chevron.render(template, values)

    def _write_file_from_template(self, path: Path, template_name: str):
        content = self._render_template(name=template_name, values=self.template_values)
        self._write_file(path=path, content=content)

    @staticmethod
    def _write_file(path: Path, content: str, allow_overwrite: bool = False):
        if path.exists() and not allow_overwrite:
            raise RuntimeError(f"File {path} exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _read_toml(path: Path) -> dict:
        with path.open("rb") as handle:
            return tomllib.load(handle)

    @staticmethod
    def _rm(path: Path):
        assert path.exists()
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            raise RuntimeError(f"Unknown path type: {path}")

    @classmethod
    def _get_remote_url(cls) -> str | None:
        remote = cls._run(["git", "config", "--get", "remote.origin.url"])

        if remote is None:
            return None
        elif remote.startswith(("https://", "http://")) and remote.endswith(".git"):
            return remote.removesuffix(".git")
        else:
            raise RuntimeError(f"Unsupported remote URL format: '{remote}'")

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str, str]:
        """https://{owner}.github.io/{repo_name} -> (owner, repo_name)"""
        parsed = urlparse(url)
        assert parsed.netloc.lower() == "github.com"
        parts = [part for part in parsed.path.split("/") if part]
        assert len(parts) == 2
        return (parts[0], parts[1])

    @classmethod
    def _get_dependencies(cls, pyproject: dict) -> list[Dependency]:
        assert "project" in pyproject

        deps = []
        if "dependencies" in pyproject["project"]:
            deps += [
                Dependency(name=name, group=None)
                for name in pyproject["project"]["dependencies"]
            ]

        if "dependency-groups" in pyproject:
            deps += [
                Dependency(name=name, group=group)
                for group, names in pyproject["dependency-groups"].items()
                for name in names
            ]

        return deps

    def _ensure_index(self) -> list[Action]:
        target = Path("docs/index.md")
        if target.exists():
            self.msg(f"[green]OK[/] {str(target)} exists")
            return []

        action = Action(
            description=f"write {str(target)}",
            fun=lambda: self._write_file_from_template(
                path=target, template_name="index.md"
            ),
        )

        return [action]

    @staticmethod
    def _find_mkdocs_yaml() -> Path | None:
        possible_paths = ["mkdocs.yaml", "mkdocs.yml"]
        paths = [Path(x) for x in possible_paths if Path(x).exists()]
        if len(paths) == 0:
            return None
        if len(paths) == 1:
            return paths[0]
        else:
            raise RuntimeError("Multiple mkdocs yaml's detected")

    def _ensure_zensical_toml(self) -> list[Action]:
        target = Path("zensical.toml")
        if target.exists():
            self.msg(f"[green]OK[/] {str(target)} already exists")
            return []

        repo_url = self._get_remote_url()
        if repo_url is not None:
            # guess owner and repo name from remote url
            repo_owner, repo_name = self._parse_github_url(repo_url)
            repo_name = self._text("Repo name", repo_name)
            repo_owner = self._text("Repo owner", repo_owner)
        else:
            # guess name from cwd, ask for owner, construct url
            repo_name = self._text("Repo name", Path.cwd().name)
            repo_owner = self._text("Repo owner", self.default_repo_owner)
            repo_url = f"https://github.com/{repo_owner}/{repo_name}"

        site_url = f"https://{repo_owner}.github.io/{repo_name}"
        self.msg(f"Using repo URL: {repo_url}")
        self.msg(f"Using site URL: {site_url}")

        python_path = "src" if Path("src").exists() else "."
        python_path = self._text("Path to Python package root", python_path)

        # if mkdocs.yaml exists, suggest copying nav from that
        if mkdocs_yaml := self._find_mkdocs_yaml():
            with open(mkdocs_yaml) as f:
                content = yaml.load(f, Loader=yaml.BaseLoader)

            assert "nav" in content
            self.template_values["nav"] = json.dumps(content["nav"])
            self.msg(f"Copying nav from {str(mkdocs_yaml)}")
        else:
            nav_paths = [str(Path(*p.parts[1:])) for p in Path("docs").glob("*.md")]
            self.template_values["nav"] = json.dumps(nav_paths)
            self.msg("Listing all docs/*.md in nav:", nav_paths)

        package_name = self._detect_package_name()
        self.template_values["project_name"] = package_name
        self.template_values["site_name"] = package_name
        self.template_values["site_url"] = site_url
        self.template_values["repo_url"] = repo_url
        self.template_values["python_path"] = python_path

        action = Action(
            description=f"create {str(target)}",
            fun=lambda: self._write_file_from_template(
                path=target, template_name="zensical.toml"
            ),
        )

        return [action]

    def _ensure_docs_workflow(self) -> list[Action]:
        path = Path(".github/workflows/docs.yaml")
        if path.exists():
            self.msg(f"[green]OK[/] {str(path)} already exists")
            return []

        action = Action(
            description=f"write {str(path)}",
            fun=lambda: self._write_file_from_template(
                path=path, template_name="docs.yaml"
            ),
        )

        return [action]

    def _cleanup_mkdocs_files(self) -> list[Action]:
        actions = []
        if mkdocs_yaml := self._find_mkdocs_yaml():
            actions.append(
                Action(f"remove {str(mkdocs_yaml)}", lambda: self._rm(mkdocs_yaml))
            )

        docs_js = Path("docs/javascript")
        if docs_js.exists():
            actions.append(Action(f"remove {str(docs_js)}", lambda: self._rm(docs_js)))

        return actions

    @staticmethod
    def _find_legacy_mkdocs_workflows() -> list[Path]:
        dir = Path(".github/workflows")
        if not dir.exists():
            return []

        paths = []
        for path in dir.rglob("*"):
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue

            if "mkdocs" in content.lower():
                paths.append(path)

        return paths

    def _cleanup_legacy_mkdocs_workflows(self) -> list[Action]:
        paths = self._find_legacy_mkdocs_workflows()
        return [Action(f"remove {str(path)}", lambda: self._rm(path)) for path in paths]

    def _readme_mentions_mkdocs(self):
        path = Path("README.md")
        if path.exists():
            content = path.read_text(encoding="utf-8")
            if "mkdocs" in content.lower():
                self.post_msgs.append(
                    f"{str(path)} contains 'mkdocs'; consider revising"
                )

    def _ensure_api_stub(self) -> list[Action]:
        path = Path("docs/api.md")
        if path.exists():
            self.msg(f"[green]OK[/] {str(path)} already exists")
            return []

        action = Action(
            description=f"write {str(path)}",
            fun=lambda: self._write_file_from_template(
                path=path, template_name="docs.yaml"
            ),
        )

        return [action]

    def _update_gitignore(self) -> list[Action]:
        path = Path(".gitignore")
        if not path.exists():
            self.msg(f"[yellow]:warning[/] {str(path)} not found")
            return []

        flag = False
        lines = [line.strip() for line in path.read_text().splitlines()]

        docs_ignore_patterns = {"docs", "docs/", "/docs", "/docs/"}
        filtered = [line for line in lines if line not in docs_ignore_patterns]
        if len(filtered) != len(lines):
            flag = True
            lines = filtered

        has_site = any(line in {"site", "site/", "/site", "/site/"} for line in lines)
        if not has_site:
            flag = True

            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.append("site/")

        if not flag:
            self.msg(f"[green]OK[/] {str(path)} is compliant")
            return []

        action = Action(
            f"update {str(path)}", lambda: path.write_text("\n".join(lines) + "\n")
        )

        return [action]

    def _run_dependency_updates(
        self, pyproject_data: dict, docs_group: str
    ) -> list[Action]:
        actions = []

        deps = self._get_dependencies(pyproject_data)

        # look for legacy dependencies
        for dep in deps:
            if dep.name in self.legacy_dep_names:
                actions.append(
                    Action(
                        f"remove legacy dependency '{dep.name}' from group '{dep.group}'",
                        lambda: self._remove_dependency(dep),
                    )
                )

        # check if doc dependencies are in the wrong group
        for dep in deps:
            if dep.name in self.docs_dep_names and dep.group != docs_group:
                actions.append(
                    Action(
                        f"remove dependency '{dep.name}' from group '{dep.group}'",
                        lambda: self._remove_dependency(dep),
                    )
                )

        # add docs to the correct group, if they don't exist
        for name in self.docs_dep_names:
            target_dep = Dependency(name, docs_group)
            if target_dep in deps:
                self.msg(f"[green]OK[/] dependency '{name}' is in group '{docs_group}'")
            else:
                actions.append(
                    Action(
                        f"add dependency '{name}' to group '{docs_group}'",
                        lambda: self._add_dependency(target_dep),
                    )
                )
        return actions

    @classmethod
    def _remove_dependency(cls, dep: Dependency):
        command = ["uv", "remove"]
        if dep.group is not None:
            command += ["--group", dep.group]
        command.append(dep.name)
        cls._run(command)

    @classmethod
    def _add_dependency(cls, dep: Dependency):
        command = ["uv", "add"]
        if dep.group is not None:
            command += ["--group", dep.group]
        command.append(dep.name)
        cls._run(command)

    @classmethod
    def _detect_package_name(cls) -> str:
        pyproject_data = cls._read_toml(Path("pyproject.toml"))
        project_name = pyproject_data["project"]["name"]
        package_name = project_name.replace("-", "_")

        if Path("src").exists():
            assert (Path("src") / package_name / "__init__.py").exists()
        else:
            assert (Path(package_name) / "__init__.py").exists()

        return package_name

    def _validate_build(self, docs_group: str | None) -> list[Action]:
        command = ["uv", "run"]

        if docs_group is not None:
            command += ["--group", docs_group]

        command += ["zensical", "build"]

        return [Action("validate build", lambda: self._run(command))]

    def run(self) -> None:
        self.msg(
            Panel.fit(
                "Set up Zensical docs in a new or existing repository",
                title="cfadoc setup",
                border_style="cyan",
            )
        )

        docs_group = self._text("Dependency group for docs packages", default="docs")
        pyproject_data = self._read_toml(Path("pyproject.toml"))

        actions: list[Action] = []

        actions += self._ensure_index()
        actions += self._ensure_api_stub()
        actions += self._ensure_zensical_toml()
        actions += self._ensure_docs_workflow()
        actions += self._update_gitignore()
        actions += self._cleanup_mkdocs_files()
        actions += self._cleanup_legacy_mkdocs_workflows()
        actions += self._run_dependency_updates(
            pyproject_data=pyproject_data, docs_group=docs_group
        )
        actions += self._validate_build(docs_group=docs_group)

        # add a post message
        self._readme_mentions_mkdocs()
        self.post_msgs.append(
            "In GitHub repo settings, set Pages source to GitHub Actions"
        )

        if not actions:
            self.msg("No actions needed")
        else:
            self.msg("\nNeeded actions:")
            for action in actions:
                self.msg("- ", action.description)
            self.msg()

            if questionary.confirm("Run these actions", default=False).ask():
                for action in actions:
                    action.fun()
                    self.msg(f"[green]OK[/] {action.description}")

                if self.post_msgs:
                    self.msg("\nSuggested manual actions:")
                    for msg in self.post_msgs:
                        self.msg("- ", msg)
            else:
                self.msg("[yellow]Cancelled[/]")


def cli():
    """Run the CLI"""
    CLI().run()
