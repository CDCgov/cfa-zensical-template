from pathlib import Path

from cfadoc import CLI


def test_create_index(tmp_path):
    project_display_name = "my_project"
    cli = CLI(root=Path(tmp_path))
    cli.template_data = {"project_display_name": project_display_name}
    actions = cli._ensure_index()
    assert len(actions) == 1
    actions[0].fun()
    path = Path(tmp_path) / "docs" / "index.md"
    assert path.exists()
    with open(path) as f:
        content = f.read()
    assert project_display_name in content
