output "contract_id" {
  description = "Non-sensitive identifier for review evidence."
  value       = local.contract_id
  sensitive   = false
}

output "target_namespace" {
  description = "Namespace expected by the render-only Helm contract."
  value       = var.namespace
  sensitive   = false
}

output "review_labels" {
  description = "Non-sensitive labels expected on a future implementation."
  value       = local.labels
  sensitive   = false
}
