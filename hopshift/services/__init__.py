"""Platform services: database, secrets, audit, settings, security, connections, deployments.

Platform code lives in this package; the pipeline packages (pipeline, cim, sources, targets,
validation) keep their responsibilities. See docs/architecture.md.
"""

from hopshift import __version__  # noqa: F401  (single source of truth)
