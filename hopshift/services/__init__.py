"""Platform services: database, secrets, audit, settings, security, connections, deployments.

New platform code lives in this package; the pipeline packages (agent, cim, providers,
validation) keep their responsibilities. See docs/platform-plan.md.
"""

from hopshift import __version__  # noqa: F401  (single source of truth)
