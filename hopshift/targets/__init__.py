"""Built-in targets. Each registers a TargetSpec; renderers live in the named package."""
from __future__ import annotations

from hopshift.targets.registry import TargetSpec, register

register(TargetSpec(
    name="aws", label="Amazon Web Services", blurb="EC2, EBS, VPC, security groups, placement groups",
    package="hopshift.targets.aws", tier="tested", tflint=True, connection_provider="aws", docs="docs/targets/aws.md",
))
register(TargetSpec(
    name="azure", label="Microsoft Azure", blurb="Virtual machines, managed disks, VNets, NSGs, availability sets",
    package="hopshift.targets.azure", tier="tested", tflint=True, connection_provider="azure", docs="docs/targets/azure.md",
))
register(TargetSpec(
    name="gcp", label="Google Cloud", blurb="Compute Engine, persistent disks, VPC, firewall rules, placement policies",
    package="hopshift.targets.gcp", tier="tested", tflint=True, connection_provider="gcp", docs="docs/targets/gcp.md",
))
register(TargetSpec(
    name="openstack", label="OpenStack", blurb="Nova, Cinder, Neutron networks, security groups, server groups",
    package="hopshift.targets.openstack", tier="validated", tflint=False, connection_provider="openstack", docs="docs/targets/openstack.md",
))
