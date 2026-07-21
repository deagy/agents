locals {
  contract_id = "${var.project_name}-${var.environment}-${var.cluster_name}"
  labels = {
    project        = var.project_name
    environment    = var.environment
    classification = var.classification
    managed_by     = "future-terraform"
  }
}
