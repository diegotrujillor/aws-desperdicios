"""One module per waste check. Each exposes IAM_ACTIONS, CHECK and main()."""
from aws_desperdicios.checks import dev_schedule, gp2_to_gp3, orphan_storage

ALL_CHECKS = (gp2_to_gp3, orphan_storage, dev_schedule)
