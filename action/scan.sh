#!/usr/bin/env bash
# Runs `modelbump scan` for the GitHub Action (action.yml, ADR 0026).
#   scan.sh sarif   write the SARIF report and set the `file` output
#   scan.sh check   print the findings, add them to the job summary, and exit 1
#                   if a model is retired or shuts down within MB_FAIL_WITHIN days
#   scan.sh bump    run `modelbump bump-all`: with MB_OPEN_PRS=true it opens one
#                   pull request per due model (ADR 0072), with dry-run it lists them
set -euo pipefail

mode="${1:-}"
args=("${MB_PATH:-.}" --soon-days "${MB_SOON_DAYS:-90}")
while IFS= read -r pattern; do
  # Trim spaces at both ends.
  pattern="${pattern#"${pattern%%[![:space:]]*}"}"
  pattern="${pattern%"${pattern##*[![:space:]]}"}"
  if [ -n "$pattern" ]; then
    args+=(--exclude "$pattern")
  fi
done <<< "${MB_EXCLUDE:-}"
if [ "${MB_SKIP_COMMENTS:-false}" = "true" ]; then
  args+=(--skip-comments)
fi
if [ "${MB_SKIP_TESTS:-false}" = "true" ]; then
  args+=(--skip-tests)
fi

# Build and run ModelBump from the action's own copy of this repository.
modelbump=(uv tool run --quiet --from "$GITHUB_ACTION_PATH" modelbump)

case "$mode" in
  sarif)
    file="$RUNNER_TEMP/modelbump.sarif"
    "${modelbump[@]}" scan "${args[@]}" --format sarif --output "$file"
    echo "file=$file" >> "$GITHUB_OUTPUT"
    ;;
  check)
    if [ -n "${MB_FAIL_WITHIN:-}" ]; then
      args+=(--fail-within "$MB_FAIL_WITHIN")
    fi
    report="$RUNNER_TEMP/modelbump.txt"
    status=0
    "${modelbump[@]}" scan "${args[@]}" > "$report" || status=$?
    cat "$report"
    {
      echo "## ModelBump"
      echo
      echo '```'
      cat "$report"
      echo '```'
    } >> "$GITHUB_STEP_SUMMARY"
    exit "$status"
    ;;
  bump)
    bump_args=("${MB_PATH:-.}" --within "${MB_WITHIN:-90}")
    for ((i = 1; i < ${#args[@]}; i++)); do
      if [ "${args[$i]}" = "--exclude" ]; then
        bump_args+=(--exclude "${args[$((i + 1))]}")
      fi
    done
    if [ "${MB_OPEN_PRS:-false}" = "true" ]; then
      bump_args+=(--open-pr)
      # Commits need an author; use the Actions bot unless the workflow set one.
      if [ -z "$(git config user.name || true)" ]; then
        git config user.name "github-actions[bot]"
        git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      fi
    fi
    report="$RUNNER_TEMP/modelbump-bump.txt"
    status=0
    "${modelbump[@]}" bump-all "${bump_args[@]}" > "$report" || status=$?
    echo "report=$report" >> "$GITHUB_OUTPUT"
    cat "$report"
    {
      echo "## ModelBump bump"
      echo
      echo '```'
      cat "$report"
      echo '```'
    } >> "$GITHUB_STEP_SUMMARY"
    exit "$status"
    ;;
  *)
    echo "usage: scan.sh sarif|check|bump" >&2
    exit 2
    ;;
esac
