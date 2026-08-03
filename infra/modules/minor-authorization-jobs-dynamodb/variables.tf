variable "table_name" {
  description = "DynamoDB table name for minor authorization validation jobs."
  type        = string
}

variable "common_tags" {
  description = "Common tags applied to resources."
  type        = map(string)
}
