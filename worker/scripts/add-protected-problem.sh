#!/usr/bin/env bash
# Adds (or updates) a protected problem: hashes a plaintext key, stores the
# hash in KV, and uploads the PDFs to the private R2 bucket.
#
# Usage:
#   ./add-protected-problem.sh <problem-id> <plaintext-key> <statement-pdf> \
#       [solution-name:solution-pdf ...]
#
# Example:
#   ./add-protected-problem.sh quiz3-p2 "fall2026-quiz3" ./statement.pdf \
#       energy-method:./sol-energy.pdf newton-method:./sol-newton.pdf
set -euo pipefail

PROBLEM_ID="$1"
PLAINTEXT_KEY="$2"
STATEMENT_PDF="$3"
shift 3

KEY_HASH=$(printf '%s' "$PLAINTEXT_KEY" | sha256sum | cut -d' ' -f1)

npx wrangler kv key put --binding=PROBLEM_KEYS "$PROBLEM_ID" \
  "{\"keyHash\":\"$KEY_HASH\"}" --remote

npx wrangler r2 object put \
  "physics-problem-bank-protected/$PROBLEM_ID/statement.pdf" \
  --file="$STATEMENT_PDF" --remote

for pair in "$@"; do
  NAME="${pair%%:*}"
  PDF_PATH="${pair#*:}"
  npx wrangler r2 object put \
    "physics-problem-bank-protected/$PROBLEM_ID/solutions/$NAME.pdf" \
    --file="$PDF_PATH" --remote
done

echo ""
echo "Added protected problem '$PROBLEM_ID'."
echo "Access key to share with students: $PLAINTEXT_KEY"
echo ""
echo "Remember to add a matching entry to docs/data/problems.json, e.g.:"
echo '  { "id": "'"$PROBLEM_ID"'", "protected": true, "statement_pdf": "statement.pdf", "solutions": [...] }'
