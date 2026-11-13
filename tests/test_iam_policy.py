"""The minimal policy must contain exactly the read-only actions the scripts use."""
import json

from aws_desperdicios.checks import ALL_CHECKS
from aws_desperdicios.cli import CORE_IAM_ACTIONS
from tests.conftest import POLICY_PATH

READ_ONLY_VERBS = ("Describe", "Get", "List")


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_policy_is_valid_iam_document():
    policy = load_policy()
    assert policy["Version"] == "2012-10-17"
    for statement in policy["Statement"]:
        assert statement["Effect"] == "Allow"
        assert statement["Resource"] == "*"


def test_policy_only_grants_read_only_actions(policy_actions):
    for action in policy_actions:
        assert action.split(":", 1)[1].startswith(READ_ONLY_VERBS), action


def test_policy_matches_exactly_the_actions_used(policy_actions):
    used = set(CORE_IAM_ACTIONS).union(*(check.IAM_ACTIONS for check in ALL_CHECKS))
    assert policy_actions == used
