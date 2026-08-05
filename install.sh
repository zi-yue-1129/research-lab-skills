#!/usr/bin/env bash
# research-lab-skills installer
# Usage (Windows: run from Git Bash or WSL, not PowerShell/cmd.exe):
#   curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --local
#   curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- uninstall
#   curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --ars-only
#   curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --lab-only
set -e

REPO="https://github.com/starpig1129/research-lab-skills.git"

# Shared foundation both lab and ARS skills depend on -- always installed
# Shared foundation both lab and ARS skills depend on -- always installed
RESOLVER_SKILLS=("resource-resolver" "agent-state")
# Lab skills (experiment journal + presentations + mode routing)
LAB_SKILLS=("research-log" "report-slides" "research-mode")
# Academic Research Skills (deep research, paper writing, review, pipeline)
ARS_SKILLS=("deep-research" "academic-paper" "academic-paper-reviewer" "academic-pipeline")
# Default: install everything
SKILLS=("${RESOLVER_SKILLS[@]}" "${LAB_SKILLS[@]}" "${ARS_SKILLS[@]}")

# ── parse args ────────────────────────────────────────────────────────────────
CMD="install"
GLOBAL=true
# True when --ars-only/--lab-only narrowed the selection; uninstall then keeps
# the shared resource-resolver foundation for whichever skills remain.
SUBSET=false
for arg in "$@"; do
  case "$arg" in
    uninstall)   CMD="uninstall" ;;
    --local)     GLOBAL=false ;;
    --ars-only)  SKILLS=("${RESOLVER_SKILLS[@]}" "${ARS_SKILLS[@]}"); SUBSET=true ;;
    --lab-only)  SKILLS=("${RESOLVER_SKILLS[@]}" "${LAB_SKILLS[@]}"); SUBSET=true ;;
  esac
done

if $GLOBAL; then
  DEST="$HOME/.claude/skills"
else
  DEST="$(pwd)/.claude/skills"
fi

# ── install ───────────────────────────────────────────────────────────────────
install_skills() {
  command -v git >/dev/null 2>&1 || { echo "Error: git is required"; exit 1; }

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  echo "Downloading research-lab-skills..."
  git clone --depth 1 "$REPO" "$TMP/repo" -q

  mkdir -p "$DEST"
  for skill in "${SKILLS[@]}"; do
    cp -r "$TMP/repo/skills/$skill" "$DEST/"
    echo "  ✓ $skill"
  done

  echo ""
  echo "Installed to: $DEST"
  echo "Restart Claude Code to activate the skills."
  echo "  Lab:      /research-log  /report-slides  /mode"
  echo "  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more"
}

# ── uninstall ─────────────────────────────────────────────────────────────────
uninstall_skills() {
  for skill in "${SKILLS[@]}"; do
    # resource-resolver is a shared dependency of both skill families. A subset
    # uninstall (--lab-only / --ars-only) must not pull it out from under the
    # skills that stay installed; only a full uninstall removes it.
    if $SUBSET && [[ " ${RESOLVER_SKILLS[*]} " == *" $skill "* ]]; then
      echo "  - Kept (shared dependency): $DEST/$skill"
      continue
    fi
    target="$DEST/$skill"
    if [ -d "$target" ]; then
      rm -rf "$target"
      echo "  ✓ Removed: $target"
    else
      echo "  - Not found (skipped): $target"
    fi
  done
  echo "Done."
}

# ── main ──────────────────────────────────────────────────────────────────────
case "$CMD" in
  install)   install_skills ;;
  uninstall) uninstall_skills ;;
esac
