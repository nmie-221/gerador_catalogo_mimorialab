output "table_name" {
  description = "Nome da tabela DynamoDB."
  value       = aws_dynamodb_table.mimorialab.name
}

output "table_arn" {
  description = "Identificador completo da tabela na AWS."
  value       = aws_dynamodb_table.mimorialab.arn
}