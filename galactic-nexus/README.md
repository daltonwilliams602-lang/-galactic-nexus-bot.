# THE GALACTIC NEXUS — hosted private test build v1.3

For running online while your PC is off, start with [HOSTING.md](HOSTING.md). This package includes a Docker build and unattended cloud launcher, with one Railway worker and one persistent volume.

**Prepared and tested locally; not yet deployed to Railway.** Your Discord bot is installed and its token connected successfully from Windows. The earlier server configuration stopped with a permission error. This build includes corrected permission checks and supports completing configuration on the host.

[START-HERE.md](START-HERE.md) retains the optional Windows instructions. Do not run a PC copy while the cloud worker is running. The owner and four founder IDs are already filled in. Role and channel IDs are discovered and recorded by the reviewed configuration run.

Read [docs/founder-test-checklist.md](docs/founder-test-checklist.md) for exact Discord tests, and [docs/pre-launch-review.md](docs/pre-launch-review.md) for the implementation and remaining gates.

67 offline checks are verified, including persistent state across restarts, preview-only setup, missing-volume rejection, duplicate-worker locking, and Linux SIGTERM cleanup. Windows skips the Linux-specific signal check. Run `python -m unittest discover -s tests -q` after installing `requirements.txt`. A Docker engine was not available in the development workspace; Railway must build the image and pass its embedded test command before live validation.

Preserve `config.local.json`, `data/`, and `backups/` when updating. Never replace a populated database with an empty one. The current launcher permits only private test mode. There is no automatic public launch, invitation, purchase, or data-reset command.
