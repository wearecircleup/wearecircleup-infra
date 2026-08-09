resource "aws_sqs_queue" "dlq" {
  name = var.dlq_name

  message_retention_seconds = 1209600

  tags = var.common_tags
}

resource "aws_sqs_queue" "this" {
  name = var.queue_name

  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  message_retention_seconds  = 1209600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.common_tags
}
