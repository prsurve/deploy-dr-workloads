#!/bin/bash
# Universal folder protection script for macOS and Linux
# Usage:
#   ./protect-folder.sh lock /path/to/folder
#   ./protect-folder.sh unlock /path/to/folder

set -e

ACTION=$1
TARGET=$2

if [[ -z "$ACTION" || -z "$TARGET" ]]; then
  echo "Usage: $0 [lock|unlock] /path/to/folder"
  exit 1
fi

if [[ ! -d "$TARGET" ]]; then
  echo "Error: '$TARGET' is not a valid directory."
  exit 2
fi

# Detect OS
OS=$(uname -s)

lock_folder() {
  echo "🔒 Locking folder: $TARGET"

  if [[ "$OS" == "Darwin" ]]; then
    sudo chflags uchg "$TARGET"
  else
    if command -v chattr >/dev/null 2>&1; then
      sudo chattr +i "$TARGET"
    fi
  fi

  # Try chmod only if not immutable
  if [[ "$OS" == "Darwin" ]]; then
    # If immutable, skip chmod (avoid errors)
    if [[ "$(ls -ldO "$TARGET" | awk '{print $5}')" != *uchg* ]]; then
      find "$TARGET" -type f -exec chmod a-w {} +
      find "$TARGET" -type d -exec chmod a+wx {} +
    else
      echo "⚠️ Skipping chmod: directory immutable (macOS)."
    fi
  else
    if [[ "$(lsattr -d "$TARGET" 2>/dev/null)" != *i* ]]; then
      find "$TARGET" -type f -exec chmod a-w {} +
      find "$TARGET" -type d -exec chmod a+wx {} +
    else
      echo "⚠️ Skipping chmod: directory immutable (Linux)."
    fi
  fi

  echo "✅ Folder locked (read/write allowed, deletion blocked)."
}


unlock_folder() {
  echo "🔓 Unlocking folder: $TARGET"

  if [[ "$OS" == "Darwin" ]]; then
    sudo chflags nouchg "$TARGET"
  else
    if command -v chattr >/dev/null 2>&1; then
      sudo chattr -i "$TARGET"
    fi
  fi

  # Restore normal permissions
  find "$TARGET" -exec chmod u+rwX,go+rX {} +

  echo "✅ Folder unlocked (full permissions restored)."
}

case "$ACTION" in
  lock)
    lock_folder
    ;;
  unlock)
    unlock_folder
    ;;
  *)
    echo "Invalid action. Use 'lock' or 'unlock'."
    exit 3
    ;;
esac
