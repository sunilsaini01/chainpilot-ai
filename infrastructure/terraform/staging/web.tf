# One address for everything: CloudFront serves the dashboard from a private S3
# bucket and sends /api/* to the load balancer. Same origin, so the SameSite=Strict
# login cookie simply works (P7-T3-R1), the API address need not be built into the
# dashboard (P6-T4-R4), and HTTPS comes with CloudFront's own domain.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "web" {
  bucket        = "${var.name}-web-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # demo days only: the files are rebuilt from Git
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Only this CloudFront distribution may read the bucket.
data "aws_iam_policy_document" "web_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.main.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web_bucket.json
}

# --- Small request rewrites at the edge ------------------------------------------------

# /api/auth/login -> /auth/login: the API keeps its paths.
resource "aws_cloudfront_function" "strip_api_prefix" {
  name    = "${var.name}-strip-api"
  runtime = "cloudfront-js-2.0"
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      request.uri = request.uri.replace(/^\/api/, "") || "/";
      return request;
    }
  JS
}

# /suppliers -> /index.html (the React router shows the page); files keep their path.
# Not done with CloudFront error pages: those would also replace the API's own 404s.
resource "aws_cloudfront_function" "spa_routes" {
  name    = "${var.name}-spa"
  runtime = "cloudfront-js-2.0"
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri.indexOf(".") === -1) {
        request.uri = "/index.html";
      }
      return request;
    }
  JS
}

# --- Headers for the dashboard (the API sets its own, app/security_headers.py) ---------

resource "aws_cloudfront_response_headers_policy" "web" {
  name = "${var.name}-web"
  security_headers_config {
    content_security_policy {
      # As apps/web/nginx.conf, with the API on the same address ('self').
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      override                   = true
    }
  }
}

# CloudFront's private way into the VPC: the internal load balancer is reached over
# AWS's own network, never the public internet (fixes P8-T1-R1). HTTP is used only
# for that private hop; viewers always use HTTPS to CloudFront.
resource "aws_cloudfront_vpc_origin" "api" {
  vpc_origin_endpoint_config {
    name                   = "${var.name}-api"
    arn                    = aws_lb.api.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# Sends cookies, query strings and headers on to the API (but not the Host header).
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  comment             = "ChainPilot AI staging (simulated data)"
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes India; PriceClass_100 does not

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = aws_lb.api.dns_name
    vpc_origin_config {
      vpc_origin_id       = aws_cloudfront_vpc_origin.api.id
      origin_read_timeout = 60 # the longest CloudFront allows without a quota request
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.web.id
    compress                   = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_routes.arn
    }
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
    compress                 = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # https://<id>.cloudfront.net
  }
}
