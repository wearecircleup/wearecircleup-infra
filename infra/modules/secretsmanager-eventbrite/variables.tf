variable "secret_name" {
  description = "Name of the Eventbrite secret."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}
