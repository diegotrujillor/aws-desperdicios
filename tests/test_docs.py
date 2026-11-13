"""Keep the documentation in sync with the real script parameters and IAM policy."""
import pytest

from aws_desperdicios.checks import ALL_CHECKS
from aws_desperdicios.cli import build_parser
from tests.conftest import REPO_ROOT

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
GUIDE = (REPO_ROOT / "docs" / "guia-de-uso.md").read_text(encoding="utf-8")
SCRIPTS = sorted(path.name for path in (REPO_ROOT / "scripts").glob("0*.py"))


def option_strings(check):
    return {
        option
        for action in build_parser(check.CHECK)._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }


def test_there_is_one_script_per_check():
    assert len(SCRIPTS) == len(ALL_CHECKS)


@pytest.mark.parametrize("script", SCRIPTS)
def test_readme_and_guide_mention_every_script(script):
    assert f"scripts/{script}" in README
    assert f"scripts/{script}" in GUIDE


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_readme_documents_every_option(check):
    for option in option_strings(check):
        assert f"`{option}" in README, option


def test_readme_lists_every_policy_action(policy_actions):
    for action in policy_actions:
        assert action in README, action


KIT_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd101aqEik32UXLvZ0tSl_t-Nk1ln0to7AU8RfdPfhwluvgPA/viewform"


def test_readme_ends_with_a_single_kit_line():
    lines = [line for line in README.splitlines() if line.strip()]
    assert README.count(KIT_FORM_URL) == 1
    assert KIT_FORM_URL in lines[-1]
    assert "[ENLACE_KIT]" not in README
