variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "dlq_name" {
  description = "Dead-letter queue name."
  type        = string
}

variable "queue_name" {
  description = "Primary SQS queue name."
  type        = string
}

variable "queue_visibility_timeout_seconds" {
  description = "Visibility timeout for the SQS queue."
  type        = number
  default     = 300
}

variable "max_receive_count" {
  description = "Maximum receive count before sending to the DLQ."
  type        = number
  default     = 3
}
