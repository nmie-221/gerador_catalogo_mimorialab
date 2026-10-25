resource "aws_dynamodb_table" "mimorialab" {
  name                        = "mimorialab-dev"
  billing_mode                = "PROVISIONED"
  read_capacity               = 1
  write_capacity              = 1
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = true

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  tags = {
    Project     = "MimoriaLab"
    Environment = "dev"
    ManagedBy   = "Terraform"
  }
}