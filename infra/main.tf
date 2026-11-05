resource "aws_dynamodb_table" "mimorialab" {
  name                        = "mimorialab-dev"
  # On-demand: pay per request, no capacity limit to hit. With 1 provisioned
  # read unit, listing products or a batch read is throttled.
  billing_mode                = "PAY_PER_REQUEST"
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