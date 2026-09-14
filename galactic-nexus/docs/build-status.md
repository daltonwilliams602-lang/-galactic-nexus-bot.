# Current build status

Supersedes the earlier build-status notes. See [pre-launch-review.md](pre-launch-review.md) for the complete implementation and [../START-HERE.md](../START-HERE.md) for the Windows setup.

The private test package now includes voice activity tracking, durable notification delivery, all 25 commands, role/channel configuration and native-safety setup, owner/founder mappings, restart safeguards, Windows launchers, and a Docker-based hosted worker. Sixty-seven offline checks are verified, including Discord permission resolution and cloud lifecycle tests.

**The bot is installed and the owner's Windows launcher connected successfully.** The screenshot confirms the intended server and owner. Configuration then stopped with Discord error 50013; the old launcher did not identify which operation failed. Normal bot startup and founder tests remain pending. The earlier browser connection is unavailable. No public launch, invitations, purchase, or progression reset has occurred through this project.

Windows fix v1.1: explicitly closes the SQLite backup handle on success and failure. Two deterministic regression checks added. Setup now distinguishes Python, dependency, and test failures.

Hosted build v1.3 supersedes the need to run setup or the bot on the PC. It includes a Dockerfile, non-interactive plan/configure/run/backup actions, mandatory volume validation, persistent configuration, single-worker locking, and graceful shutdown. Railway connection is confirmed, but deployment commands did not become available in this session. No paid service was created. See [../HOSTING.md](../HOSTING.md) for hosting, migration, and verification. Docker image build and actual hosted Discord operation remain unverified.

Setup fix v1.2: checks permissions required by role grants and channel allow/deny settings before Discord mutations, including permissions lost when @everyone is restricted. Lists missing toggles and temporary permissions to remove. Skips matching role edits and identifies failed API operations. Adds five regression checks and corrects the omitted thread permissions. These fixes are included in hosted v1.3; offline checks do not establish live success.
