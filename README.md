# Galactic Nexus bot

Private founder-testing Discord community system for **THE GALACTIC NEXUS**.

Application code and Dockerfile are in [`galactic-nexus/`](galactic-nexus/).
Railway's source root is `/galactic-nexus`.

- [Hosting and troubleshooting](galactic-nexus/HOSTING.md)
- [Feature and permission review](galactic-nexus/docs/pre-launch-review.md)
- [Founder acceptance checklist](galactic-nexus/docs/founder-test-checklist.md)

The worker requires persistent storage at `/data`; never disable this check to
repair hosting. A build success does not prove the Discord bot is online.

From `galactic-nexus/`, run `python -m unittest discover -s tests -q` for offline
validation. Read-only Discord diagnosis uses `python -m nexus.diagnose` with the
bot credential supplied privately through `NEXUS_TOKEN`.

Keep credentials, local configuration, databases, backups, and private review
files out of Git. Public launch requires a separate owner approval after founder
testing.
