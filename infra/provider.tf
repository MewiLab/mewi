# WHICH cloud provider and region?
#
# Why a separate file:
#   Changing cloud region is a big decision. Keeping it isolated
#   means you can find and change it instantly without reading
#   through resource definitions.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
