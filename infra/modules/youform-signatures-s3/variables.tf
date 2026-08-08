variable "bucket_name" {
  description = "Private S3 bucket name used to store copied YouForm signature images."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "purpose_tag" {
  description = "Purpose tag applied to the private bucket."
  type        = string
  default     = "youform-signatures"
}

variable "object_lock_retention_years" {
  description = "Default Object Lock retention period, in years, applied in COMPLIANCE mode to every stored signature."
  type        = number
  default     = 100
}
