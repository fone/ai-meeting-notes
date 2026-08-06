#!/usr/bin/env bash
# Compatibility entry point. Provider selection now happens in the app's
# Settings screen so API keys are not echoed, written to shell startup files,
# or used to replace the recording configuration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Cloud provider setup is now handled in the app: Settings → AI Models."
echo "This bootstrap preserves the production Turbo transcription default."
exec "$ROOT/setup.sh" "$@"
