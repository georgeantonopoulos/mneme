# Install And Update Mneme For Hermes

This guide is for a Hermes operator or Hermes bootstrap job that needs the
Mneme skill to run reliably on a machine.

Hermes needs two things:

1. The `mneme` CLI installed and on `PATH`.
2. The complete `skills/mneme-agent-brain/` skill directory available to Hermes.

The skill directory alone is not enough. The helper script inside the skill
delegates to the repository readiness script at `scripts/hermes_brain_ready.sh`,
so Hermes also needs either a Mneme checkout or `MNEME_REPO` pointing at one.

## Files Hermes Must Have

Keep this directory together as one unit:

```text
skills/mneme-agent-brain/
  SKILL.md
  references/
    operator-flow.md
    install-update.md
  scripts/
    mneme_brain_smoke.sh
```

Do not copy only `SKILL.md`. The runbook and smoke helper are part of the
operator contract.

The Mneme checkout must also include:

```text
scripts/hermes_brain_ready.sh
src/mneme/
pyproject.toml
```

## Recommended Install Or Update

Use the repository installer to install or update the CLI:

```bash
curl -fsSL https://raw.githubusercontent.com/georgeantonopoulos/mneme/main/scripts/install.sh | bash
```

The installer clones or updates the checkout at:

```text
~/.local/share/mneme
```

It installs the CLI as:

```text
~/.local/bin/mneme
```

If Hermes runs with a restricted environment, export the path explicitly:

```bash
export PATH="$HOME/.local/bin:$PATH"
export MNEME_REPO="$HOME/.local/share/mneme"
```

## Install The Skill Directory

If Hermes can load a skill directly from the checkout, point it at:

```text
$MNEME_REPO/skills/mneme-agent-brain
```

If Hermes requires skills to be copied into its own skills directory, copy the
whole folder:

```bash
mkdir -p "$HERMES_SKILLS_DIR"
rm -rf "$HERMES_SKILLS_DIR/mneme-agent-brain"
cp -R "$MNEME_REPO/skills/mneme-agent-brain" "$HERMES_SKILLS_DIR/mneme-agent-brain"
```

Use an atomic staging directory if Hermes may read skills while the update is
running:

```bash
tmp_dir="$HERMES_SKILLS_DIR/.mneme-agent-brain.tmp"
rm -rf "$tmp_dir"
cp -R "$MNEME_REPO/skills/mneme-agent-brain" "$tmp_dir"
rm -rf "$HERMES_SKILLS_DIR/mneme-agent-brain"
mv "$tmp_dir" "$HERMES_SKILLS_DIR/mneme-agent-brain"
```

## Verify The Install

Check the CLI:

```bash
mneme --help
mneme contract check --db "$DB"
```

Check the skill files:

```bash
test -f "$HERMES_SKILLS_DIR/mneme-agent-brain/SKILL.md"
test -f "$HERMES_SKILLS_DIR/mneme-agent-brain/references/operator-flow.md"
test -f "$HERMES_SKILLS_DIR/mneme-agent-brain/references/install-update.md"
test -x "$HERMES_SKILLS_DIR/mneme-agent-brain/scripts/mneme_brain_smoke.sh"
```

Run the skill smoke helper against an existing Mneme database:

```bash
MNEME_REPO="$MNEME_REPO" \
MNEME_BRAIN_DEPTH=smoke \
"$HERMES_SKILLS_DIR/mneme-agent-brain/scripts/mneme_brain_smoke.sh" \
  "$DB" "$PROMPT"
```

The smoke helper must reach the repository readiness script and complete:

```text
mneme consolidate
mneme brain label
mneme brain report
mneme contract check
mneme retrieve
mneme surface
mneme agent preflight
```

Before using Mneme memory in an answer, Hermes should also run:

```bash
mneme agent preflight --db "$DB" --prompt "$PROMPT"
```

Use Mneme memory as factual grounding only when the returned
`contract.status` is `pass`.

## Update Checklist

- [ ] Run the Mneme installer or update the checkout with `git pull --ff-only`.
- [ ] Make sure `mneme --help` works in the same environment Hermes uses.
- [ ] Refresh the complete `skills/mneme-agent-brain/` directory if Hermes uses copied skills.
- [ ] Export `MNEME_REPO` when the skill directory is outside the Mneme checkout.
- [ ] Run `mneme contract check --db "$DB"`.
- [ ] Run the skill smoke helper with `MNEME_BRAIN_DEPTH=smoke`.
- [ ] Run `mneme agent preflight --db "$DB" --prompt "$PROMPT"` and confirm `contract.status` is `pass`.

## Failure Modes

If the smoke helper says it cannot find `scripts/hermes_brain_ready.sh`, set:

```bash
export MNEME_REPO=/absolute/path/to/mneme
```

If Hermes can see the skill but `mneme` is missing, update Hermes' `PATH` or
install Mneme with `scripts/install.sh`.

If `contract.status` is `fail`, do not use Mneme memory as factual grounding.
Run `mneme contract check --db "$DB"` and fix the reported graph invariant.
