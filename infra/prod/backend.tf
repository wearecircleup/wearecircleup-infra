terraform {
  backend "s3" {
    bucket       = "wearecircleup-terraform-state-311923415472-us-east-1"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
