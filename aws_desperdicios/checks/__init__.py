"""One module per waste check. Each exposes IAM_ACTIONS, CHECK and main()."""
from aws_desperdicios.checks import gp2_to_gp3

ALL_CHECKS = (gp2_to_gp3,)
