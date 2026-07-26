import importlib.resources

import chevron

MODULE = "cfadocs.resources"


def get(path_names: list[str]) -> str:
    """Get a resource"""
    return importlib.resources.read_text(MODULE, *path_names, encoding="utf-8")


def template(path_names: list[str], data: dict) -> str:
    """Template a resource"""
    return chevron.render(template=get(path_names), data=data)
