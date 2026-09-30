#!/usr/bin/env bash
# Copy the Claude Code and Cursor configuration (rules, agents, skills) into another
# repository, for when the exercise comes with its own codebase.
#
#   scripts/install-into.sh /path/to/their-repo
#
# Existing files in the target are never overwritten.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <target-repo>" >&2
  exit 2
fi

source_dir="$(cd "$(dirname "$0")/.." && pwd)"
target="$1"

if [[ ! -d "$target" ]]; then
  echo "error: $target is not a directory" >&2
  exit 1
fi

copy_if_absent() {
  local from="$1" to="$2"
  if [[ -e "$to" ]]; then
    echo "kept     $to (already exists)"
  else
    mkdir -p "$(dirname "$to")"
    cp "$from" "$to"
    echo "copied   $to"
  fi
}

copy_if_absent "$source_dir/CLAUDE.md" "$target/CLAUDE.md"

while IFS= read -r -d '' file; do
  relative="${file#"$source_dir"/}"
  copy_if_absent "$file" "$target/$relative"
done < <(find "$source_dir/.claude" "$source_dir/.cursor" -type f ! -name 'settings.local.json' -print0)

copy_if_absent "$source_dir/.cursorignore" "$target/.cursorignore"

mkdir -p "$target/brief"

if [[ ! -e "$target/AGENTS.md" ]]; then
  cat > "$target/AGENTS.md" <<'EOF'
# Repository guide

Not written yet. Before the first change, inspect this repository (layout, entry points,
test and lint commands, dependency manager, conventions) and follow what is already here.
The layout described in .claude/rules/architecture.md and in the skills is a default for new
code, not something to impose on existing code.
EOF
  echo "created  $target/AGENTS.md (stub: tells Claude to follow the existing repo)"
fi

cat <<EOF

Done. Next:
  cd "$target" && claude        (or open the folder in Cursor)
  then: "Inspect this repository and rewrite AGENTS.md with its real commands and layout."
EOF
