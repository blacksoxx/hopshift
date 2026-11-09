#!/usr/bin/env bash
# Fake `terraform` for unit tests (tests/vma/test_deploy_service.py, tests/api/test_deploy_api.py).
#
# Records every invocation to $FAKE_TF_LOG (one tab-separated line: cwd, argv, selected env)
# and emits output shaped like the real binary. Behaviour is selected with FAKE_TF_MODE:
#   ok (default)  init/plan/show/apply/destroy succeed; plan exits 2 (changes present)
#   no_changes    plan exits 0 and reports no changes
#   init_fail     init exits 1 with a provider error
#   plan_fail     plan exits 1 with a credentials error
#   apply_fail    apply exits 1 mid-way
#   sleep         plan/apply/destroy block (for cancel and timeout tests)
#   leak          plan prints secret-looking values (for masking tests)
set -u
mode="${FAKE_TF_MODE:-ok}"
cmd="${1:-}"
if [ -n "${FAKE_TF_LOG:-}" ]; then
  printf 'cwd=%s\targv=%s\tTF_DATA_DIR=%s\tTF_IN_AUTOMATION=%s\tTF_INPUT=%s\tTF_PLUGIN_CACHE_DIR=%s\tAWS_ACCESS_KEY_ID=%s\tAWS_PROFILE=%s\n' \
    "$(pwd)" "$*" "${TF_DATA_DIR:-}" "${TF_IN_AUTOMATION:-}" "${TF_INPUT:-}" "${TF_PLUGIN_CACHE_DIR:-}" \
    "${AWS_ACCESS_KEY_ID:-}" "${AWS_PROFILE:-}" >> "$FAKE_TF_LOG"
fi

plan_out=""
for arg in "$@"; do
  case "$arg" in
    -out=*) plan_out="${arg#-out=}" ;;
  esac
done

write_state() {
  mkdir -p ../state
  cat > ../state/terraform.tfstate <<JSON
{"version":4,"terraform_version":"1.8.5","serial":$1,"lineage":"4f0c1d2e-fake","resources":$2}
JSON
}

case "$cmd" in
  version)
    echo "Terraform v1.8.5"
    exit 0 ;;
  init)
    if [ "$mode" = "init_fail" ]; then
      echo "Initializing the backend..."
      echo "Error: Failed to query available provider packages" >&2
      echo "Could not retrieve the list of available versions for provider hashicorp/aws" >&2
      exit 1
    fi
    echo "Initializing the backend..."
    echo "Initializing provider plugins..."
    echo "- Using previously-installed hashicorp/aws v6.0.0"
    echo "Terraform has been successfully initialized!"
    printf 'provider "registry.terraform.io/hashicorp/aws" {\n  version = "6.0.0"\n}\n' > .terraform.lock.hcl
    exit 0 ;;
  plan)
    if [ "$mode" = "sleep" ]; then exec sleep 60; fi
    if [ "$mode" = "leak" ]; then
      echo "aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY:-unset}"
      echo "session token: ${AWS_SESSION_TOKEN:-none}"
      echo "db_password = hunter2-plain"
      echo "region = us-east-1"
    fi
    if [ "$mode" = "plan_fail" ]; then
      echo "aws_vpc.main: Refreshing state..."
      echo "Error: configuring Terraform AWS Provider: no valid credential sources for Terraform AWS Provider found." >&2
      exit 1
    fi
    [ -n "$plan_out" ] && echo "fake-plan" > "$plan_out"
    if [ "$mode" = "no_changes" ]; then
      echo "No changes. Your infrastructure matches the configuration."
      exit 0
    fi
    echo "aws_vpc.main: Refreshing state... [id=vpc-123]"
    echo ""
    echo "Terraform will perform the following actions:"
    echo "  # aws_vpc.main will be created"
    echo ""
    echo "Plan: 2 to add, 1 to change, 1 to destroy."
    exit 2 ;;
  show)
    cat <<'JSON'
{"format_version":"1.2","terraform_version":"1.8.5","variables":{"aws_region":{"value":"us-east-1"},"db_password":{"value":"hunter2-plain"}},"resource_changes":[{"address":"aws_vpc.main","mode":"managed","type":"aws_vpc","name":"main","change":{"actions":["create"]}},{"address":"aws_subnet.a","mode":"managed","type":"aws_subnet","name":"a","change":{"actions":["create"]}},{"address":"aws_instance.web","mode":"managed","type":"aws_instance","name":"web","change":{"actions":["update"]}},{"address":"aws_instance.old","mode":"managed","type":"aws_instance","name":"old","change":{"actions":["delete"]}},{"address":"aws_ebs_volume.data","mode":"managed","type":"aws_ebs_volume","name":"data","change":{"actions":["delete","create"]}},{"address":"aws_security_group.x","mode":"managed","type":"aws_security_group","name":"x","change":{"actions":["no-op"]}}]}
JSON
    exit 0 ;;
  apply)
    if [ "$mode" = "sleep" ]; then exec sleep 60; fi
    plan_file="${@: -1}"
    if [ ! -f "$plan_file" ]; then
      echo "Error: saved plan file $plan_file not found" >&2
      exit 1
    fi
    echo "aws_vpc.main: Creating..."
    if [ "$mode" = "apply_fail" ]; then
      echo "Error: creating EC2 VPC: UnauthorizedOperation: You are not authorized to perform this operation." >&2
      exit 1
    fi
    echo "aws_vpc.main: Creation complete after 1s [id=vpc-123]"
    echo "aws_subnet.a[\"x\"]: Creating..."
    echo "aws_subnet.a[\"x\"]: Creation complete after 1s [id=subnet-123]"
    write_state 3 '[{"mode":"managed","type":"aws_vpc","name":"main","provider":"provider[\"registry.terraform.io/hashicorp/aws\"]","instances":[{"schema_version":1,"attributes":{"id":"vpc-123"}}]},{"mode":"managed","type":"aws_subnet","name":"a","provider":"provider[\"registry.terraform.io/hashicorp/aws\"]","instances":[{"index_key":"x","schema_version":1,"attributes":{"id":"subnet-123"}}]}]'
    echo ""
    echo "Apply complete! Resources: 2 added, 1 changed, 1 destroyed."
    exit 0 ;;
  destroy)
    if [ "$mode" = "sleep" ]; then exec sleep 60; fi
    echo "aws_vpc.main: Destroying... [id=vpc-123]"
    echo "aws_vpc.main: Destruction complete after 1s"
    write_state 4 '[]'
    echo ""
    echo "Destroy complete! Resources: 2 destroyed."
    exit 0 ;;
  *)
    echo "fake terraform: unsupported command '$cmd'" >&2
    exit 1 ;;
esac
