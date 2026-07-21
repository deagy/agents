# Validate-only Terraform Contract

This directory describes inputs and non-sensitive derived outputs for a future Proxmox/Talos/Kubernetes implementation. It contains no backend, provider, resources, data lookups, provisioners, state operations, plan, or apply behavior.

Run only static validation:

```sh
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
python -B -m unittest discover -s infra/tests -p "test_*.py"
```

`init -backend=false` installs nothing because the contract declares no providers. It is validation setup, not infrastructure initialization. Do not add credentials or use this directory for a plan/apply until the open production decisions and human gates are resolved.
