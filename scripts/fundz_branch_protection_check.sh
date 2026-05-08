#!/usr/bin/env zsh
set -euo pipefail

REPO="${1:-afundsolution/fundz}"
BRANCH="${2:-main}"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required: gh"
  exit 2
fi

echo "Checking branch protection for $REPO:$BRANCH"

if protection="$(gh api "repos/$REPO/branches/$BRANCH/protection" 2>&1)"; then
  echo "$protection" | grep -q '"contexts"' || true
  echo "Branch protection is enabled."
  echo "$protection"
  exit 0
fi

echo "$protection"

if echo "$protection" | grep -qi "Upgrade to GitHub Pro"; then
  cat <<'EOF'

GitHub blocked branch protection for this private repository.

To require the Memory Check workflow, use one of these options:
1. Upgrade the GitHub account/repo plan so private-repo branch protection is available.
2. Make the repository public if that is acceptable.
3. Keep relying on the existing Memory Check GitHub Action until branch protection is available.

After the plan supports it, enable protection for main and require the
"memory-check" status check before merging.
EOF
  exit 3
fi

exit 1
