variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}

variable "domain" {
  description = "Domain to verify in SES."
  type        = string
}
