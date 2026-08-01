variable "table_name" {
  description = "DynamoDB table name for normalized YouForm submissions."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}
