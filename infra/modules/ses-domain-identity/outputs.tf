output "domain" {
  description = "Verified SES domain."
  value       = var.domain
}

output "identity_arn" {
  description = "SES domain identity ARN."
  value       = aws_ses_domain_identity.this.arn
}

output "verification_token" {
  description = "SES verification token for the TXT record."
  value       = aws_ses_domain_identity.this.verification_token
}

output "verification_record" {
  description = "DNS TXT record required to verify the SES domain identity."
  value = {
    type  = "TXT"
    name  = "_amazonses.${var.domain}"
    value = aws_ses_domain_identity.this.verification_token
  }
}

output "dkim_tokens" {
  description = "SES DKIM tokens for the domain."
  value       = aws_ses_domain_dkim.this.dkim_tokens
}

output "dkim_records" {
  description = "DNS CNAME records required for SES DKIM."
  value = [
    for token in aws_ses_domain_dkim.this.dkim_tokens : {
      type  = "CNAME"
      name  = "${token}._domainkey.${var.domain}"
      value = "${token}.dkim.amazonses.com"
    }
  ]
}
