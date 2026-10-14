#!/usr/bin/env bash
# Store the shared-hosting deploy settings in GitHub and start the first deploy.
#
#   scripts/setup-deploy.sh            ask for every value (the password is not echoed)
#
# Values can also come from the environment (FTP_SERVER, FTP_USERNAME, FTP_PASSWORD,
# FTP_SERVER_DIR, SITE_URL, FTP_PROTOCOL, FTP_PORT); only missing ones are asked for.
# Needs the GitHub CLI (`gh auth login`). Secret values are passed on stdin, never as arguments.
set -euo pipefail

command -v gh >/dev/null || { echo "GitHub CLI 'gh' is required: https://cli.github.com" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first." >&2; exit 1; }
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
echo "Configuring deploy settings for $repo"

ask() {  # ask VAR "prompt" [default] [secret]
  local var=$1 prompt=$2 default=${3:-} secret=${4:-} value=${!1:-}
  while [ -z "$value" ]; do
    if [ -n "$secret" ]; then
      read -r -s -p "$prompt: " value; echo
    else
      read -r -p "$prompt${default:+ [$default]}: " value
      value=${value:-$default}
    fi
  done
  printf -v "$var" '%s' "$value"
}

ask FTP_SERVER     "FTP server (e.g. ftp.yourdomain.com)"
ask FTP_USERNAME   "FTP username (e.g. deploy@yourdomain.com)"
ask FTP_PASSWORD   "FTP password" "" secret
ask FTP_SERVER_DIR "Folder on the server, relative to the FTP account's home" "./"
ask SITE_URL       "Public site URL (e.g. https://yourdomain.com/cobol)"
ask FTP_PROTOCOL   "Protocol (ftps or ftp)" "ftps"
ask FTP_PORT       "FTP port" "21"

case "$FTP_SERVER_DIR" in */) ;; *) FTP_SERVER_DIR="$FTP_SERVER_DIR/" ;; esac
SITE_URL=${SITE_URL%/}
case "$SITE_URL" in https://*|http://*) ;; *) echo "SITE_URL must start with https://" >&2; exit 1 ;; esac
case "$FTP_PROTOCOL" in ftps|ftp) ;; *) echo "Protocol must be ftps or ftp" >&2; exit 1 ;; esac

for name in FTP_SERVER FTP_USERNAME FTP_PASSWORD FTP_SERVER_DIR; do
  printf '%s' "${!name}" | gh secret set "$name" --repo "$repo"
done
gh variable set SITE_URL --repo "$repo" --body "$SITE_URL"
gh variable set FTP_PROTOCOL --repo "$repo" --body "$FTP_PROTOCOL"
gh variable set FTP_PORT --repo "$repo" --body "$FTP_PORT"
echo "Secrets and variables saved."

read -r -p "Start the deploy now? [Y/n] " go
if [ "${go:-Y}" != n ] && [ "${go:-Y}" != N ]; then
  gh workflow run deploy.yml --repo "$repo" --ref main
  echo "Deploy started. Follow it with: gh run watch \$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
fi
