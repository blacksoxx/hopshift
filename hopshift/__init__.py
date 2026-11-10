"""hopshift: migrate infrastructure from any source to any target through one canonical model.

Packages: cim (the canonical model), sources (discovery translators), targets (renderers per
destination), pipeline (the LangGraph run), validation (terraform, tflint, OPA), services
(platform: accounts, audit, connections, deployments, compliance), api, cli.
"""

__version__ = "0.1.0"
