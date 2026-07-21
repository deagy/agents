variable "project_name" {
  description = "Lowercase name used in future SAMPLE-001 resource naming."
  type        = string
  default     = "sample-001"

  validation {
    condition     = can(regex("^[a-z](?:[a-z0-9-]{1,29}[a-z0-9])$", var.project_name))
    error_message = "project_name must be 3-31 lowercase letters, digits, or hyphens."
  }
}

variable "environment" {
  description = "The contract is deliberately limited to local or test use."
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "test"], var.environment)
    error_message = "Only local or test environments are permitted."
  }
}

variable "cluster_name" {
  description = "Future Talos/Kubernetes cluster identifier; no lookup is performed."
  type        = string

  validation {
    condition     = can(regex("^[a-z](?:[a-z0-9-]{1,61}[a-z0-9])$", var.cluster_name))
    error_message = "cluster_name must be a valid lowercase DNS label."
  }
}

variable "namespace" {
  description = "Future namespace; this contract does not create it."
  type        = string
  default     = "sample-001"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "namespace must be a valid Kubernetes DNS label."
  }
}

variable "classification" {
  description = "Non-secret classification label used for review metadata."
  type        = string
  default     = "internal"

  validation {
    condition     = contains(["public", "internal", "confidential"], var.classification)
    error_message = "classification must be public, internal, or confidential."
  }
}
