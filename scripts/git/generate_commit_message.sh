#!/usr/bin/env bash
# Generate a draft git commit message from changes in this repository (vibe-coding-files).
# Uses path heuristics only (no network / LLM). Edit the output before committing.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: generate_commit_message.sh [options]

Draft a commit message from repo changes (heuristic subject + file list). No LLM; edit before commit.

Options:
  --staged     Staged diff only (default when the index has changes).
  --worktree   Unstaged diff only (working tree vs index).
  --all        All uncommitted changes vs HEAD (staged + unstaged).
  --copy, -c   Copy full message to clipboard (xclip / wl-copy / pbcopy / clip.exe).
  -o FILE      Write message to FILE (UTF-8).
  -h, --help   Show this help.

If nothing is staged but the worktree has changes, default mode is --worktree.
EOF
}

MODE=""
COPY=false
OUT_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --staged) MODE=staged; shift ;;
        --worktree) MODE=worktree; shift ;;
        --all) MODE=all; shift ;;
        --copy | -c) COPY=true; shift ;;
        -o)
            OUT_FILE=${2:?}
            shift 2
            ;;
        -h | --help) usage; exit 0 ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "Error: not inside a git repository." >&2
    exit 1
}
cd "$REPO_ROOT"

has_staged=false
has_work=false
git diff --cached --quiet 2>/dev/null || has_staged=true
git diff --quiet 2>/dev/null || has_work=true

if [[ -z "$MODE" ]]; then
    if $has_staged; then
        MODE=staged
    elif $has_work; then
        MODE=worktree
    else
        echo "No staged or unstaged changes." >&2
        exit 0
    fi
fi

# staged = index vs HEAD; worktree = work tree vs index; all = everything not yet committed vs HEAD
case "$MODE" in
    staged) NAME_STATUS=$(git diff --cached --name-status) ;;
    worktree) NAME_STATUS=$(git diff --name-status) ;;
    all) NAME_STATUS=$(git diff HEAD --name-status) ;;
    *)
        echo "Internal error: bad MODE=$MODE" >&2
        exit 1
        ;;
esac

if [[ -z "${NAME_STATUS//[$'\t\n\r ']/}" ]]; then
    echo "No changes for mode: $MODE" >&2
    if [[ "$MODE" == staged ]] && $has_work; then
        echo "Hint: working tree has changes; try: $0 --worktree" >&2
    fi
    exit 0
fi

# --- stats ---
added=0
modified=0
deleted=0
renamed=0
while IFS= read -r line; do
    [[ -z "${line// }" ]] && continue
    st=$(echo "$line" | awk '{print $1}')
    case "$st" in
        A) added=$((added + 1)) ;;
        M) modified=$((modified + 1)) ;;
        D) deleted=$((deleted + 1)) ;;
        R*)
            renamed=$((renamed + 1))
            modified=$((modified + 1))
            ;;
        C*)
            modified=$((modified + 1))
            ;;
        *) ;; # U, etc.
    esac
done <<<"$NAME_STATUS"

verb=update
if [[ $deleted -gt 0 && $added -eq 0 && $modified -eq 0 ]]; then
    verb=remove
elif [[ $added -gt 0 && $modified -eq 0 && $deleted -eq 0 ]]; then
    verb=add
fi

# Strip optional double quotes from git path tokens (name-status / quoted paths).
strip_q() {
    local p="$1"
    p="${p#\"}"
    p="${p%\"}"
    printf '%s' "$p"
}

# Dominant top-level directory (first path component)
top_scope=$(
    echo "$NAME_STATUS" |
        awk 'NF>=2 { print $NF }' |
        while IFS= read -r p; do
            p=$(strip_q "$p")
            [[ -z "$p" ]] && continue
            if [[ "$p" == */* ]]; then
                echo "${p%%/*}"
            else
                echo "root"
            fi
        done |
        sort | uniq -c | sort -rn | awk 'NR==1 {print $2}'
)

if [[ -z "$top_scope" ]]; then
    top_scope=chore
fi

# Short hint from up to 2 basenames
basenames=""
first=true
while IFS= read -r b; do
    [[ -z "$b" ]] && continue
    if $first; then
        basenames="$b"
        first=false
    else
        basenames+=", $b"
        break
    fi
done < <(
    echo "$NAME_STATUS" |
        awk 'NF>=2 { print $NF }' |
        while IFS= read -r p; do
            p=$(strip_q "$p")
            [[ -n "$p" ]] && basename "$p"
        done | sort -u | head -2
)

nfiles=$(echo "$NAME_STATUS" | awk 'NF>=2' | wc -l | tr -d ' ')

hint=""
if [[ -n "$basenames" ]] && [[ $nfiles -le 2 ]]; then
    hint=" ($basenames)"
elif [[ $nfiles -le 5 ]]; then
    hint=" ($nfiles files)"
else
    hint=" ($nfiles files)"
fi

subject="${top_scope}: ${verb}${hint}"

# Keep subject roughly conventional (lowercase scope word)
subject=$(echo "$subject" | head -c 72)

# --- build full message ---
MSG=""
MSG+="${subject}"$'\n'$'\n'

stats="Staged/worktree: ${MODE}. "
stats+="Added ${added}, modified ${modified}, deleted ${deleted}"
[[ $renamed -gt 0 ]] && stats+=", renamed ${renamed}"
MSG+="${stats}."$'\n'$'\n'

MSG+="Paths:"$'\n'
while IFS= read -r line; do
    [[ -z "${line// }" ]] && continue
    MSG+="  ${line}"$'\n'
done <<<"$NAME_STATUS"

MSG+=$'\n'"---"$'\n'
MSG+="Generated by scripts/git/generate_commit_message.sh (${MODE})."$'\n'
MSG+="Replace subject/body; keep imperative mood and scope if using Conventional Commits."$'\n'

emit() {
    printf '%s' "$MSG"
}

if [[ -n "$OUT_FILE" ]]; then
    emit >"$OUT_FILE"
    echo "Wrote: $OUT_FILE" >&2
fi

if $COPY; then
    if command -v xclip >/dev/null 2>&1; then
        emit | xclip -selection clipboard
        echo "Copied to clipboard (xclip)." >&2
    elif command -v wl-copy >/dev/null 2>&1; then
        emit | wl-copy
        echo "Copied to clipboard (wl-copy)." >&2
    elif command -v pbcopy >/dev/null 2>&1; then
        emit | pbcopy
        echo "Copied to clipboard (pbcopy)." >&2
    elif command -v clip.exe >/dev/null 2>&1; then
        emit | clip.exe
        echo "Copied to clipboard (clip.exe)." >&2
    else
        echo "No clipboard tool found; printing to stdout only." >&2
        emit
    fi
elif [[ -z "$OUT_FILE" ]]; then
    emit
fi
