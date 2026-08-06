#!/usr/bin/env bash
# Compatibility entry point. Provider selection now happens in the app's
# Settings screen so credentials are stored once, config is not overwritten,
# and the production Turbo default is preserved.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Local provider setup is now handled in the app: Settings → AI Models."
echo "This bootstrap installs the recording and Turbo transcription path first."
exec "$ROOT/setup.sh" "$@"
