#!/bin/sh
set -eu

escape_js_single_quoted() {
  printf '%s' "$1" | sed -e "s/\\\\/\\\\\\\\/g" -e "s/'/\\\\'/g"
}

api_base_url="${AVOCADO_API_BASE_URL:-/api/v1}"
escaped_api_base_url=$(escape_js_single_quoted "$api_base_url")

cat > /usr/share/nginx/html/env.js <<EOF
window.__AVOCADO_CONFIG__ = {
  apiBaseUrl: '$escaped_api_base_url',
}
EOF