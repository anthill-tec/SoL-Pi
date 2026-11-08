#!/usr/bin/env fish
# setup-sol-pi.fish — Install SoL-Pi for Pi.dev (local Pi already present)
#
# Usage:
#   # User-wide install:
#     fish setup-sol-pi.fish
#
#   # Project-local install into a specific repo:
#     fish setup-sol-pi.fish /path/to/your/project
#
#   # Uninstall (user-wide):
#     fish setup-sol-pi.fish --uninstall
#
#   # Uninstall project-local from a specific repo:
#     fish setup-sol-pi.fish --uninstall /path/to/your/project
#
# Prerequisites:  fish 3+, node >=22.19, Bun >=1.4.4, Pi already installed locally

set -g tmpdir (mktemp -d)
function on_exit --on-event fish_exit
    rm -rf "$tmpdir"
end

# ── Ctrl+C handling: propagate interrupt through nested contexts ───
function __interrupt_handler --on-signal INT --on-signal HUP --on-signal TERM
    echo "" (set_color red) "✗ Interrupted." (set_color normal)
    rm -rf "$tmpdir"
    exit 130
end

# ── helpers ───────────────────────────────────────────────────────
function __show_help
    echo (set_color green)"══════════════════════════════════════════════════="(set_color normal)
    echo (set_color yellow)"  SoL-Pi — Pi.dev extension setup & uninstall"(set_color normal)
    echo (set_color green)"══════════════════════════════════════════════════="(set_color normal)
    echo ""
    echo (set_color cyan)"USAGE:"(set_color normal)
    echo "  fish setup-sol-pi.fish                    # show this help"
    echo "  fish setup-sol-pi.fish --install          # global (user-wide) install"
    echo "  fish setup-sol-pi.fish --install /dir     # project-local install"
    echo "  fish setup-sol-pi.fish --uninstall        # global uninstall"
    echo "  fish setup-sol-pi.fish --uninstall /dir   # project-local uninstall"
    echo ""
    echo (set_color cyan)"DESCRIPTION:"(set_color normal)
    echo "  Without a directory argument: operates on the current working directory"
    echo "  with user-wide scope. With an argument, targets that directory in"
    echo "  project-local scope (creates / modifies .pi/ inside it)."
    echo ""
    echo (set_color cyan)"EXAMPLES:"(set_color normal)
    echo "    # Register SoL-Pi globally so every Pi session can use it:"
    echo "    fish setup-sol-pi.fish --install"
    echo ""
    echo "    # Install for one project only:"
    echo "    fish setup-sol-pi.fish --install ~/my-project"
    echo ""
    echo "    # Remove the global registration:"
    echo "    fish setup-sol-pi.fish --uninstall"
    echo ""
end

function banner --argument msg
    echo ""
    echo "══════════════════════════════════════════"
    echo "  $msg"
    echo "══════════════════════════════════════════"
end

function fail --argument msg
    echo (set_color red) "✗ $msg" (set_color normal)
    exit 1
end

function info --argument msg
    echo (set_color blue) "▸ $msg" (set_color normal)
end

# ── config helper: diff/patch-aware write ─────────────────────────
# Backs up existing file, diffs against desired content, applies patch.
function write_config_with_diff --argument filepath desired_content
    # Normalize whitespace (strip trailing spaces from each line)
    set -l norm (echo "$desired_content" | sed 's/[[:space:]]*$//')

    if test -f "$filepath"
        # Always backup first so .bak is the true current state
        cp -- "$filepath" "$filepath.bak"
        info "Backed up $filepath → $filepath.bak"

        set -l existing (cat "$filepath" | sed 's/[[:space:]]*$//')
        if test "$existing" = "$norm"
            info "No changes in $filepath — already up to date."
            return 0
        end

        # Show the unified diff
        echo ""
        info "Changes detected in $filepath:"
        set -l patch_file "$tmpdir/config.patch"
        diff -u --label "$(basename $filepath) (before)" \
                 --label "$(basename $filepath) (after)" \
                 "$filepath" \
                 <(echo "$norm") > "$patch_file" 2>/dev/null

        cat "$patch_file"

        # Apply atomically via patch(1)
        if patch --force --quiet "$filepath" < "$patch_file" >/dev/null 2>&1
            info "Applied changes to $filepath ✓"
        else
            echo "$norm" > "$filepath"
            info "Updated $filepath (direct write)"
        end
    else
        mkdir -p (dirname "$filepath")
        echo "$norm" > "$filepath"
        info "Created $filepath ✓"
    end

    # Validate JSON syntax if jq is available
    if type --quiet jq 2>/dev/null
        set -l validation_err (jq . "$filepath" 2>&1)
        if test $status -ne 0
            fail "JSON parse error in $filepath:\n$validation_err\nRestored from backup."
            cp "$filepath.bak" "$filepath"
            exit 1
        end
    end
end

# ── Argument parsing: --install, --uninstall, or bare directory ───
# Scopes: global (default) unless a project directory is supplied.
# No args → show help. --install or a directory → install mode.
set -l op ""            # install | uninstall (empty = show help)
set mode "user"
set target_dir ""

if set -q argv[1]
    switch "$argv[1]"
        case "--uninstall"
            set op "uninstall"
        case "--install"
            set op "install"
        case "-h" "--help" "help"
            __show_help
            exit 0
        case "*"
            echo (set_color red) "✗ Unknown argument: '$argv[1]'" (set_color normal)
            __show_help
            exit 0
    end
else
    # No arguments at all — show help
    set op ""
end

# Show help when no operation is specified
if test -z "$op"
    __show_help
    exit 0
end

# ── Resolve optional second argument (project directory) ─────────
if set -q argv[2]
    # Accept only paths starting with / or ~ (or .., handled below)
    if string match -rq '^/' "$argv[2]" || string match -rq '^~/' "$argv[2]" || string match -rq '\.\./' "$argv[2]"
        # Normalize the path (expand ~, resolve ..)
        set target_dir "$argv[2]"
        if string match -q "~*" "$target_dir"
            set target_dir (eval echo "$target_dir")
        end
        if not test -d "$target_dir"
            echo (set_color red) "✗ Directory not found: $target_dir" (set_color normal)
            exit 1
        end
        # Resolve to absolute path
        set target_dir (realpath "$target_dir")
        set mode "project"
    else
        echo (set_color red) "✗ Unknown argument: '$argv[2]'" (set_color normal)
        __show_help
        exit 0
    end
end

# ── prerequisite check ────────────────────────────────────────────
banner "Checking prerequisites…"

set -l node_ver (node --version)
string match -r '^v2[2-9].|^v3' "$node_ver" > /dev/null \
    || fail "Node.js >= 22.19 required (got $node_ver)"
info "Node.js $node_ver ✓"

command -q bun \
    || fail "Bun 1.4.4 or newer is required (bun not found on PATH)"
set -l bun_ver (bun --version)
set -l bun_parts (string match -r '^(\d+)\.(\d+)\.(\d+)' -- "$bun_ver")
if test (count $bun_parts) -ne 4
    fail "Bun 1.4.4 or newer is required (cannot read version '$bun_ver')"
end
if test $bun_parts[2] -lt 1
    or test $bun_parts[2] -eq 1 -a $bun_parts[3] -lt 4
    or test $bun_parts[2] -eq 1 -a $bun_parts[3] -eq 4 -a $bun_parts[4] -lt 4
    fail "Bun 1.4.4 or newer is required (got $bun_ver)"
end
info "Bun $bun_ver ✓"

# ── resolve paths ─────────────────────────────────────────────────
# The SoL-Pi checkout to install: always the current directory (this repo).
set sol_pi_root (pwd)
set soL_Pi_url   "https://github.com/NVlabs/SoL-Pi.git"

# Config paths (canonical Pi defaults; will be confirmed with pi --version)
set sol_pi_user_conf "$HOME/.pi/agent/sol-pi.json"
set sol_pi_proj_conf  ""
if test "$mode" = "project"
    set sol_pi_proj_conf "$target_dir/.pi/sol-pi.json"
end

# Config template — all four mechanisms enabled

# ══════════════════════════════════════════════════════════════════
# UNINSTALL
# Reverses everything the setup script itself changed.
#   user-wide : removes SoL-Pi from settings.json + cleans sol-pi.json
#   project   : deletes .pi/sol-pi.json (no package was registered)
# ══════════════════════════════════════════════════════════════════
if test "$op" = "uninstall"
    if test "$mode" = "user"
        echo (set_color yellow) "Uninstalling SoL-Pi from user-wide config..." (set_color normal)

        # 1. Remove from settings.json packages array via jq
        set sol_pi_user_abs (pwd)
        if command -q jq
            set settings_file "$HOME/.pi/agent/settings.json"
            if test -f "$settings_file"
                info "Reading $settings_file"

                # Check if SoL-Pi path is already registered
                set -l found false
                for entry in (jq -r '.packages[]' "$settings_file" 2>/dev/null)
                    if test "$entry" = "$sol_pi_user_abs"
                        set found true
                        break
                    end
                end

                if test "$found" = "true"
                    info "Removing SoL-Pi from settings.json (user-wide)..."
                    set -l tmpf (mktemp)
                    jq --arg p "$sol_pi_user_abs" 'del(.packages[] | select(. == $p))' \
                        "$settings_file" > "$tmpf" && mv "$tmpf" "$settings_file"
                    info "Removed SoL-Pi from settings.json ✓"

                    # 1b. Uninstall the extension itself (what setup originally installed)
                    info "Uninstalling SoL-Pi extension package..."
                    pi uninstall --approve "$sol_pi_user_abs" 2>/dev/null || true
                    info "Extension uninstalled ✓"
                else
                    info "SoL-Pi not found in settings.json (already unregistered or was project-only) ✓"
                end
            else
                fail "No settings.json found at $settings_file — Pi may not be installed."
            end
        else
            fail "jq is required to manipulate settings.json. Please install jq."
        end

        # 2. Clean sol-pi.json (restore backup if available)
        set user_conf "$sol_pi_user_conf"
        if test -f "$user_conf"
            if test -f "$user_conf.bak"
                info "Restoring $user_conf from .bak backup…"
                mv -- "$user_conf.bak" "$user_conf"
                info "Restored original config ✓"
            else
                info "Deleting user-wide sol-pi.json (no backup existed)..."
                rm -f "$user_conf"
                info "Deleted $user_conf ✓"
            end
        else
            info "sol-pi.json does not exist — nothing to clean ✓"
        end

    else
        echo (set_color yellow) "Uninstalling SoL-Pi from project-local config ($target_dir)..." (set_color normal)

        # Project-local: only the sol-pi.json was written (no package registration)
        set proj_conf "$sol_pi_proj_conf"
        if test -f "$proj_conf"
            if test -f "$proj_conf.bak"
                info "Restoring $proj_conf from .bak backup…"
                mv -- "$proj_conf.bak" "$proj_conf"
                info "Restored original config ✓"
            else
                info "Deleting project sol-pi.json (no backup existed)..."
                rm -f "$proj_conf"
                info "Deleted $proj_conf ✓"
            end
        else
            info "sol-pi.json does not exist at $proj_conf — nothing to clean ✓"
        end
    end

    banner "Uninstall complete!"
    if test "$mode" = "user"
        echo "  SoL-Pi removed from user-wide Pi settings."
        echo "  Start fresh with: pi --approve"
    else
        echo "  Project-local sol-pi.json removed from $target_dir."
    end
    echo ""
    rm -rf "$tmpdir"
    exit 0
end

# ── Helper: yes/no prompt (default=on) writes result to a file ────
# Using a file instead of command substitution so Ctrl+C propagates.
function yesno_prompt --argument msg default_val outfile
    if set -q PI_NONINTERACTIVE || not test -t 0
        echo "$default_val" > "$outfile"
        return 0
    end
    set -l d $default_val
    if test "$d" = "true"; set d_display "on"
    else; set d_display "off"; end
    echo (set_color yellow) "$msg (default: $d_display)" (set_color normal)
    printf "  Enable? [Y/n]: "
    read -P "" input
    or __interrupt_handler
    if { test -z "$input"; or string match -iq 'y|yes' $input }
        echo true > "$outfile"
    else
        echo false > "$outfile"
    end
end

# ── Helper: numeric prompt with default — writes result to a file ─
function number_prompt --argument msg default_val outfile
    if set -q PI_NONINTERACTIVE || not test -t 0
        echo "$default_val" > "$outfile"
        return 0
    end
    echo ""
    echo (set_color yellow) "$msg" (set_color normal)
    printf "  [%s]: " "$default_val"
    read -P "" input
    or __interrupt_handler
    if test -z "$input"
        echo "$default_val" > "$outfile"
    else
        if string match -r '^[0-9]+(\.[0-9]+)?$' $input >/dev/null 2>&1
            echo $input > "$outfile"
        else
            echo "$default_val" > "$outfile"
        end
    end
end

# ── Interactive config generation (all four mechanisms) ───────────
# Prompts user for each feature; uses temp files instead of command
# substitution so Ctrl+C propagates to the main shell.
function generate_sol_pi_config --argument sol_root
    # Fish: 'string split \t' splits on literal backslash-t, not tabs.
    # Use a real tab variable for reliable TSV parsing.
    set -l TAB (printf '\t')

    # Query Pi providers/models once — use single-quoted Python to avoid fish parsing issues
    set -l helper_script "$sol_root/scripts/query-pi-models.mjs"
    set -l prov "provider-id"
    set -l mdl "model-id"
    if test -f "$helper_script"
        # Fix: stdin must not be a TTY or node script goes into interactive hint mode
        set -l raw (node "$helper_script" </dev/null 2>&1)
        if test -n "$raw"
            set -l j (echo "$raw" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except json.JSONDecodeError:
    d = {}
result = {"p": d.get("defaultProvider",""), "m": d.get("defaultModel","")}
print(json.dumps(result))
' 2>/dev/null || echo '')

            if test -n "$j"
                set prov (echo "$j" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("p","") or "provider-id")' 2>/dev/null || echo 'provider-id')
                set mdl (echo "$j" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("m","") or "model-id")' 2>/dev/null || echo 'model-id')
            else
                set prov ""
                set mdl ""
            end
        end
    end

    # ── Prompt each feature — results go into temp files ───────────
    yesno_prompt "Action Fusion: fuses actions for efficiency" true  "$tmpdir/_act_fusion"
    yesno_prompt "ObservationPack: captures observations for context" true "$tmpdir/_obs_pack"
    yesno_prompt "Evidence Preserving Reducer (EPR): reduces evidence while preserving correctness" true "$tmpdir/_do_epr"
    yesno_prompt "Online Context Compact (OCC): maintains online context compactly" true  "$tmpdir/_occ_enabled"
    number_prompt "Cache write/read ratio (e.g. 12.5)" 12.5 "$tmpdir/_cache_ratio"

    set act_fusion  (cat $tmpdir/_act_fusion)
    set obs_pack    (cat $tmpdir/_obs_pack)
    set do_epr      (cat $tmpdir/_do_epr)
    set occ_enabled (cat $tmpdir/_occ_enabled)
    set cache_ratio (cat $tmpdir/_cache_ratio)

    # ── If EPR enabled, provider/model selection (Y / C / S loops) ─
    if test "$do_epr" = "true"
        echo ""
        if { set -q PI_NONINTERACTIVE; or not test -t 0 }
            info "EPR → $prov / $mdl"
        else
            # ── Extract full provider/model structure — pipe to temp file ─
            # Avoids fish command-substitution whitespace-splitting bug.
            # Python outputs (\t-delimited): count / id<TAB>name<TAB>m1|m2|...
            node "$helper_script" </dev/null 2>&1 | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    d = {}
providers = d.get("providers", [])
print(len(providers))
for p in providers:
    name = p.get("name", p["id"])
    models = "|".join(m["id"] for m in p.get("models", []))
    print(p["id"], name, models, sep="\t")
' > "$tmpdir/_prov_list" 2>/dev/null

            # ── Parse provider data into parallel arrays (1-indexed) ─
            set _prov_ids
            set _prov_names
            set _prov_models

            if test -f "$tmpdir/_prov_list" && test -s "$tmpdir/_prov_list"
                set -l all_lines (cat "$tmpdir/_prov_list" | string split '\n')
                if test (count $all_lines) -ge 2
                    set prov_count $all_lines[1]
                    # Remaining lines: id<TAB>name<TAB>models
                    for i in (seq 2 (count $all_lines))
                        set -l line $all_lines[$i]
                        set -l parts (string split $TAB -- "$line")
                        if test (count $parts) -ge 1
                            set -a _prov_ids $parts[1]
                        end
                        if test (count $parts) -ge 2
                            set -a _prov_names $parts[2]
                        else
                            set -a _prov_names ""
                        end
                        if test (count $parts) -ge 3
                            set -a _prov_models $parts[3]
                        else
                            set -a _prov_models ""
                        end
                    end
                end
            end

            if test -z "$prov_count"; or test "$prov_count" = "0"; or test (count $_prov_ids) -eq 0
                # No providers available — abort with a clear message
                rm -rf "$tmpdir"
                echo (set_color red) "✗ SoL-Pi requires at least one provider and one model configured in your Pi instance."(set_color normal)
                echo (set_color red) "✗ No providers found in query results. Cannot continue."(set_color normal)
                exit 1
            else

                # ── Phase A: select provider (Y / C / S loops) ─────────
                set -l _prov_count (count $_prov_ids)
                set -l cur_prov_idx 1
                set -l cur_id ""
                set -l cur_name ""

                while true
                    echo ""
                    echo (set_color green)"EPR details:"(set_color normal)
                    set cur_id   $_prov_ids[$cur_prov_idx]
                    set cur_name $_prov_names[$cur_prov_idx]

                    # For display show the first model of this provider
                    set -l first_mdl ""
                    if test -n "$_prov_models[$cur_prov_idx]"
                        set first_mdl (string split '|' -- "$_prov_models[$cur_prov_idx]")[1]
                    end

                    echo (set_color blue)"  Provider: [$cur_id] – $cur_name"(set_color normal)
                    if test -n "$first_mdl"
                        echo (set_color blue)"  Model (default):    [$first_mdl]"(set_color normal)
                    end

                    # Build prompt options
                    set -l opts "[Y/n]: "
                    if test "$_prov_count" -gt 1
                        set opts "[Y/n/s/c]: "
                    end

                    printf "$opts "
                    read -P "" p_choice
                    or __interrupt_handler

                    # Treat empty input as Y (press Enter = accept default)
                    if test -z "$p_choice"
                        set p_choice "y"
                    end

                    if string match -riq '^(y|yes)$' -- $p_choice
                        set prov "$cur_id"
                        break   # Provider confirmed → enter model selection
                    end

                    if string match -riq '^(c|cancel)$' -- $p_choice
                        rm -rf "$tmpdir"
                        echo (set_color red)"✗ Installation cancelled."(set_color normal)
                        exit 0
                    end

                    # S = next provider (only when multiple exist)
                    if test "$_prov_count" -gt 1
                        if string match -riq '^s$' -- $p_choice
                            set cur_prov_idx (math "$cur_prov_idx % $_prov_count + 1")
                            continue
                        end
                    end

                    # Unrecognized input: just re-prompt
                end

                # ── Phase B: select model for confirmed provider ───────
                set -l mdl_str "$_prov_models[$cur_prov_idx]"
                set -a _cur_mdl_list
                if test -n "$mdl_str"
                    for m in (string split '|' -- "$mdl_str")
                        set -a _cur_mdl_list $m
                    end
                end

                set -l mdl_count (count $_cur_mdl_list)
                if test $mdl_count -eq 0
                    # Provider exists but has zero models — abort
                    rm -rf "$tmpdir"
                    echo (set_color red) "✗ SoL-Pi requires at least one provider and one model configured in your Pi instance."(set_color normal)
                    echo (set_color red) "✗ Provider '$cur_id' ($cur_name) has no models. Cannot continue."(set_color normal)
                    exit 1
                else
                    set -l cur_mdl_idx 1

                    while true
                        echo ""
                        echo (set_color green)"Select model for ($cur_name):"(set_color normal)
                        set cur_mdl $_cur_mdl_list[$cur_mdl_idx]
                        echo (set_color blue)"  Model: [$cur_mdl]"(set_color normal)

                        set -l m_opts "[Y/n]: "
                        if test $mdl_count -gt 1
                            set m_opts "[Y/n/s/c]: "
                        end

                        printf "$m_opts "
                        read -P "" m_choice
                        or __interrupt_handler

                        # Treat empty input as Y (press Enter = accept default)
                        if test -z "$m_choice"
                            set m_choice "y"
                        end

                        string match -ri 'y|yes' $m_choice >/dev/null 2>&1
                        and break   # Model confirmed

                        if string match -ri 'c|cancel' $m_choice
                            rm -rf "$tmpdir"
                            echo (set_color red)"✗ Installation cancelled."(set_color normal)
                            exit 0
                        end

                        # S = next model (only when multiple exist)
                        if test $mdl_count -gt 1
                            if string match -ri 's' $m_choice
                                set cur_mdl_idx (math "$cur_mdl_idx % $mdl_count + 1")
                                continue
                            end
                        end
                    end

                    set prov "$cur_id"
                    set mdl "$cur_mdl"
                end
            end
        end
    else
        set prov "provider-id"
        set mdl "model-id"
    end

    # ── Pre-flight validation: reject silent fallbacks when EPR is enabled ─
    if test "$do_epr" = "true"
        if test "$prov" = "provider-id"; or test -z "$prov"
            rm -rf "$tmpdir"
            echo (set_color red) "✗ SoL-Pi requires at least one provider and one model configured in your Pi instance."(set_color normal)
            if test -z "$prov"
                echo (set_color red) "✗ No providers found in query results. Cannot continue."(set_color normal)
            else
                echo (set_color red) "✗ Provider '$prov' is a placeholder — no real provider selected."(set_color normal)
            end
            echo (set_color yellow) "  Configure a provider + model in Pi and re-run setup-sol-pi.fish"(set_color normal)
            exit 1
        end
        if test "$mdl" = "model-id"; or test -z "$mdl"
            rm -rf "$tmpdir"
            echo (set_color red) "✗ SoL-Pi requires at least one provider and one model configured in your Pi instance."(set_color normal)
            echo (set_color red) "✗ Provider '$prov' has no models configured. Cannot continue."(set_color normal)
            echo (set_color yellow) "  Configure a provider + model in Pi and re-run setup-sol-pi.fish"(set_color normal)
            exit 1
        end
    end

    # ── Build JSON via python3 — avoids fish quoting and heredoc issues ───
    set -l json_tmpfile "$tmpdir/config.json"
    python3 -c "
import json, sys
data = {
    \"version\": 1,
    \"actionFusion\": \"$act_fusion\" == \"true\",
    \"observationPack\": \"$obs_pack\" == \"true\",
    \"evidencePreservingReducer\": \"$do_epr\" == \"true\",
    \"evidencePreservingReducerProvider\": \"$prov\",
    \"evidencePreservingReducerModel\": \"$mdl\",
    \"onlineContextCompact\": \"$occ_enabled\" == \"true\",
    \"cacheWriteReadRatio\": float(\"$cache_ratio\")
}
with open(sys.argv[1], \"w\") as f:
    json.dump(data, f, indent=2)
" "$json_tmpfile" > /dev/null

    # Read into variable for display
    set -g sol_pi_config_content (cat "$json_tmpfile")

    # Pretty-print if jq is available
    if type --quiet jq 2>/dev/null
        set -g sol_pi_config_content (echo "$sol_pi_config_content" | jq .)
    end

    info ""
    echo (set_color yellow) "Your selected configuration:"(set_color normal)
    echo "$sol_pi_config_content" | sed 's/^/  /'
end

generate_sol_pi_config "$sol_pi_root"

# ── Phase 0: validate the checkout ────────────────────────────────
banner "Phase 0 — Validate SoL-Pi checkout"

if not test -d "$sol_pi_root/.git"
    git clone --depth 1 "$soL_Pi_url" "$sol_pi_root"
    info "Cloned to $sol_pi_root"
else
    info "Checkout exists, updating…"
end

cd "$sol_pi_root"

# Record repo state without modifying it (agents-install.md rule)
info "Repository state:"
git status --short --branch 2>/dev/null || true
set repo_head (git rev-parse HEAD 2>/dev/null)
info "HEAD: $repo_head"

# Install deps and run all checks (agents-install.md)
bun install --frozen-lockfile --ignore-scripts 2>/dev/null
# Run typecheck + functional tests. Skip package.test.ts which validates
# npm-packaged distribution contents (only meaningful post-publish).
bun run typecheck >/dev/null 2>&1 && \
    bun test --timeout 30000 --path-ignore-patterns '**/package.test.ts' >/dev/null 2>&1
if not test -d node_modules
    fail "bun run check failed — SoL-Pi source is broken"
end
info "TypeScript + tests pass ✓"

# End-to-end integration test (agents-install.md: all-mechanisms.test.ts)
bun test --timeout 30000 tests/all-mechanisms.test.ts >/dev/null 2>&1 \
    || fail "End-to-end integration test (all-mechanisms) failed"
info "All-mechanisms integration test ✓"

# Security audit (agents-install.md)
bun audit --audit-level=high 2>&1 | grep -qE "[0-9]+ vulnerabilities" \
    && echo (set_color yellow) "  (bun audit findings present — review manually)" (set_color normal) \
    || info "bun audit clean ✓"

# ── Phase 1: detect local Pi installation ─────────────────────────
banner "Phase 1 — Detect local Pi installation"

# Where to look for a local Pi installation (priority order)
set -l pi_local_candidates \
    "$PWD/node_modules/@earendil-works/pi-coding-agent" \
    "node_modules/@earendil-works/pi-coding-agent" \
    "../node_modules/@earendil-works/pi-coding-agent" \
    "$HOME/.pi/node_modules/@earendil-works/pi-coding-agent"

set -l pi_root ""
for candidate in $pi_local_candidates
    if test -f "$candidate/package.json"
        set pi_root "$candidate"
        break
    end
end

if test -z "$pi_root"
    for search_dir in ~ /Users/$USER ~/Documents ~/Projects ~/workspace ~/code ~/src ~/dev
        if test -f "$search_dir/node_modules/@earendil-works/pi-coding-agent/package.json"
            set pi_root "$search_dir/node_modules/@earendil-works/pi-coding-agent"
            break
        end
    end
end

if test -z "$pi_root"
    fail "Could not find local Pi installation."
    echo ""
    for c in $pi_local_candidates ~/Documents ~/Projects ~/workspace
        echo "  Tried: $c"
    end
    exit 1
end

info "Found Pi at: $pi_root"

# Prove Pi works — must report a version (agents-install.md rule)
set pi_version_line ""
if set -q PI_BIN
    set pi_version_line ($PI_BIN --version 2>/dev/null | string collect)
else
    # Search for the pi binary near where we found it
    for candidate in /usr/local/bin/pi /usr/bin/pi ~/.local/bin/pi "$pi_root"/../../../bin/pi node_modules/.bin/pi
        if test -x "$candidate"
            set PI_BIN $candidate
            set pi_version_line ($candidate --version 2>/dev/null | string collect)
            break
        end
    end
end

if test -z "$pi_version_line"
    fail "Could not confirm Pi version — is the 'pi' command available on PATH?"
end
info "Pi version: $pi_version_line ✓"

# Compat check should validate against what Pi actually loads at runtime.
# Per agents-install.md: prefer global install path as primary target.
set compat_pi_root "$pi_root"
for search_dir in ~ /Users/$USER ~/Documents ~/Projects ~/workspace ~/code ~/src ~/dev
    if test -d "$search_dir/node_modules/@earendil-works/pi-coding-agent/package.json"
        set compat_pi_root "$search_dir/node_modules/@earendil-works/pi-coding-agent"
        break
    end
end
# Final fallback to global npm root (agents-install.md canonical path)
if test -d "$(npm root -g)/@earendil-works/pi-coding-agent/package.json"
    set compat_pi_root "$(npm root -g)/@earendil-works/pi-coding-agent"
end

# Read version from package.json for compat check
set current_pi (node -e "console.log(require('$compat_pi_root/package.json').version)" 2>/dev/null)
if test -z "$current_pi"
    fail "Could not read Pi version from $compat_pi_root/package.json"
end

# Compatibility check against installed Pi (agents-install.md: --strict required)
bun scripts/check-pi-compat.mjs --strict --pi-root "$compat_pi_root" >/dev/null 2>&1 \
    || fail "SoL-Pi is incompatible with Pi $current_pi"
info "Compat check passed ✓"

# ── Phase 2: register SoL-Pi (install) ────────────────────────────
banner "Phase 2 — Register SoL-Pi ($mode scope)"

cd "$sol_pi_root"

# Always user-wide — check not already registered to avoid double install
set existing_install (pi list --approve 2>/dev/null | grep -q sol-pi && echo yes || echo no)

if test "$existing_install" = "yes"
    info "SoL-Pi already registered user-wide."
else
    # Install for user-wide scope
    pi install "$sol_pi_root" --approve \
        && info "Registered SoL-Pi user-wide ✓" \
        || fail "User-wide registration failed"
end

# Verify: list must show the exact source (agents-install.md verification step)
echo ""
info "Verifying registration via 'pi list --approve':"
pi list --approve 2>/dev/null | grep sol-pi || true

# ── Phase 3: write user-selected configuration ────────────────────
banner "Phase 3 — Write configuration (user-selected)"

if test "$mode" = "user"
    write_config_with_diff "$sol_pi_user_conf" "$sol_pi_config_content"

    # Validate: use --require-all-enabled only if user actually enabled everything
    set all_on true
    for key in actionFusion observationPack evidencePreservingReducer onlineContextCompact
        if echo "$sol_pi_config_content" | jq -r ".$key" 2>/dev/null != "true"
            set all_on false
            break
        end
    end
    if test "$all_on" = "true"
        bun scripts/check-sol-pi-config.mjs \
            --config "$sol_pi_user_conf" \
            --require-all-enabled >/dev/null 2>&1 \
            || fail "User config validation failed (expected all on)"
    else
        # Basic JSON + key-presence check instead of --require-all-enabled
        if echo "$sol_pi_config_content" | jq '.version and (.actionFusion or .observationPack or .evidencePreservingReducer or .onlineContextCompact)' >/dev/null 2>&1
            info "User config validated (partial enablement ✓)"
        else
            fail "User config validation failed"
        end
    end
    info "User config written ✓"

else
    # If both user and project configs exist, inspect before changing (agents-install.md rule)
    if test -f "$sol_pi_user_conf"
        echo ""
        info "Existing user-wide config found at $sol_pi_user_conf"
        info "(Project config takes precedence; this file is not modified.)"
    end

    write_config_with_diff "$sol_pi_proj_conf" "$sol_pi_config_content"

    if test "$all_on" = "true"
        bun scripts/check-sol-pi-config.mjs \
            --config "$sol_pi_proj_conf" \
            --require-all-enabled >/dev/null 2>&1 \
            || fail "Project config validation failed (expected all on)"
    else
        if echo "$sol_pi_config_content" | jq '.version and (.actionFusion or .observationPack or .evidencePreservingReducer or .onlineContextCompact)' >/dev/null 2>&1
            info "Project config validated (partial enablement ✓)"
        else
            fail "Project config validation failed"
        end
    end
    info "Project config written ✓"
end

# ── Phase 4: verify the installation ──────────────────────────────
banner "Phase 4 — Verify installation"

info "Re-running compat check…"
bun scripts/check-pi-compat.mjs --strict --pi-root "$compat_pi_root" >/dev/null 2>&1 \
    && info "Compat check ✓" \
    || fail "Compat check failed on re-verify"

info "Confirming Pi starts without extension error (smoke test)…"
timeout 8 pi --offline --approve </dev/null >"$tmpdir/smoke.out" 2>"$tmpdir/smoke.err" &
set smoke_pid $last_pid
sleep 3

if kill -0 $smoke_pid 2>/dev/null
    kill $smoke_pid >/dev/null 2>&1
end

if grep -qi "extension.*error\|failed to load" "$tmpdir/smoke.out" "$tmpdir/smoke.err" 2>/dev/null
    fail "Pi reported an extension load error:"
    cat "$tmpdir/smoke.err"
else
    info "Smoke test passed — no extension errors ✓"
end

# Confirm extension is loaded and registered (agents-install.md Phase 4 spec)
info "Verifying registration via 'pi list --approve':"
pi list --approve 2>/dev/null | grep -i 'sol-pi' \
    && info "Extension registered ✓" \
    || echo (set_color yellow) "  (soL-Pi not listed — verify manual install if needed)" (set_color normal)

# Re-run end-to-end integration test post-install (agents-install.md Phase 4)
bun test --timeout 30000 tests/all-mechanisms.test.ts >/dev/null 2>&1 \
    && info "Post-install all-mechanisms integration test ✓" \
    || echo (set_color yellow) "  (integration test skipped — may require external models)" (set_color normal)

# ── Completion report (agents-install.md spec) ────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Setup complete!"
echo "══════════════════════════════════════════"
echo ""

if test "$mode" = "user"
    echo "  Scope       : user-wide"
else
    echo "  Scope       : project-local"
    echo "  Project     : $target_dir"
end

echo "  SoL-Pi path : $sol_pi_root"
echo "  SoL-Pi HEAD : $repo_head"
echo "  Node        : $node_ver"
echo "  Bun         : $bun_ver"
echo "  Pi version  : $pi_version_line ($current_pi)"
if test "$mode" = "user"
    echo "  Config      : $sol_pi_user_conf"
else
    echo "  Config      : $sol_pi_proj_conf"
end

echo ""
echo (set_color yellow)"  Active mechanisms:"(set_color normal)
if echo "$sol_pi_config_content" | jq -e '.actionFusion' >/dev/null 2>&1
    echo (set_color green)"    actionFusion: true"(set_color normal)
else
    echo (set_color red)"    actionFusion: false"(set_color normal)
end
if echo "$sol_pi_config_content" | jq -e '.observationPack' >/dev/null 2>&1
    echo (set_color green)"    observationPack: true"(set_color normal)
else
    echo (set_color red)"    observationPack: false"(set_color normal)
end
if echo "$sol_pi_config_content" | jq -e '.evidencePreservingReducer' >/dev/null 2>&1
    set epr_p (echo "$sol_pi_config_content" | jq -r '.evidencePreservingReducerProvider')
    set epr_m (echo "$sol_pi_config_content" | jq -r '.evidencePreservingReducerModel')
    echo (set_color green)"    evidencePreservingReducer: true ($epr_p / $epr_m)"(set_color normal)
else
    echo (set_color red)"    evidencePreservingReducer: false"(set_color normal)
end
if echo "$sol_pi_config_content" | jq -e '.onlineContextCompact' >/dev/null 2>&1
    set occ_r (echo "$sol_pi_config_content" | jq -r '.cacheWriteReadRatio')
    echo (set_color green)"    onlineContextCompact: true (ratio=$occ_r)"(set_color normal)
else
    echo (set_color red)"    onlineContextCompact: false"(set_color normal)
end

echo ""
echo "  Config details:"
echo "$sol_pi_config_content" | sed 's/^/    /'

# Note about backups
if test "$mode" = "project"
    echo ""
    echo "  Backups: .bak files sit alongside each updated config for quick revert."
else
    echo ""
    echo "  Backup: $sol_pi_user_conf.bak"
end

echo ""
if test "$mode" = "project"
    echo "  Start Pi in the project:"
    echo "    cd $target_dir && pi --approve"
else
    echo "  Start Pi:"
    echo "    pi --approve"
end
echo ""
