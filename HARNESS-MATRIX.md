# Harnesses being benchmarked

**Current scope (2026-10-10): 6 trials, MCP only.** Claude Opus / Claude Code + FreeCAD MCP and GPT-6.1 Sol / Codex + FreeCAD MCP each use all three drawings. Sol replaces Astra in the active scope, and its three trials run first. Baseline and verification-skill arms below describe the historical plan. Old Astra artifacts remain unchanged. No systemd service or timer is installed.

| Active setup | Model | Agent version | Drawings |
| --- | --- | --- | --- |
| `claude-code-opus--freecad-mcp` | `claude-opus-5-5` | Claude Code 2.1.289 | All 3 |
| `codex-sol-6-1--freecad-mcp` | `gpt-6.1-sol` | Codex 0.162.1 | All 3 |

New experiment: `mcp-3-sol-v1`. Reasoning remains high; FreeCAD remains 1.1.0. Model access probe returned OK. Official model documentation: https://developers.openai.com/api/docs/models/gpt-6.1-sol .

Here, **harness** means the agent plus any added skills or tools. The model is recorded separately. Every setup receives the same original Harbor drawing-only instruction and the same three examples.

## Historical six-setup plan

| Setup ID | Model | Coding agent | Added skill/tool |
| --- | --- | --- | --- |
| `claude-code-opus` | Claude Opus 5.5 (`claude-opus-5-5`) | Claude Code 2.1.289 | None: baseline |
| `claude-code-opus--verification-skill` | Claude Opus 5.5 | Claude Code 2.1.289 | Superpowers `verification-before-completion` skill |
| `claude-code-opus--freecad-mcp` | Claude Opus 5.5 | Claude Code 2.1.289 | FreeCAD MCP: document inspection, code execution, and visual feedback |
| `codex-astra` | GPT-6 Astra (`gpt-6-astra`) | Codex CLI 0.161.0 | None: baseline |
| `codex-astra--verification-skill` | GPT-6 Astra | Codex CLI 0.161.0 | Superpowers `verification-before-completion` skill |
| `codex-astra--freecad-mcp` | GPT-6 Astra | Codex CLI 0.161.0 | FreeCAD MCP: document inspection, code execution, and visual feedback |

**Six setups × three examples = 18 primary trials.** Baseline, skill, and tool are separate arms: the skill and MCP tool are not bundled. A model's enhanced setup is compared against that same model's baseline.

## Skill details

**Superpowers: verification-before-completion**

- Source: https://github.com/obra/superpowers
- Frozen commit: `8ca22dba9a94f28898bbce59f2537ff4d87c747d`
- Only this one skill is installed, not the entire framework.
- The agent is explicitly told to use the skill before declaring completion.
- Tests the effect of demanding fresh verification evidence.
- No hidden reference CAD, specifications, or grader are provided to the skill.

## Tool details

**FreeCAD MCP by neka-nat**

- Source: https://github.com/neka-nat/freecad-mcp
- Frozen commit: `4751f953636f46b825424320c2f76e11159dd8c0`
- Source package version: `0.1.26`; MCP SDK dependency: `2.3.0`.
- The server and FreeCAD GUI run in the isolated task container using Xvfb, not on the user's desktop.
- Exposes document/object creation and editing, live inspection, GUI/headless code execution, and image feedback.
- Excludes `insert_part_from_library` and `get_parts_list`: the drawing remains the only source of geometry.
- Excludes unrelated FEM analysis.
- The exact exposed tool list is recorded by the smoke test in `runs/mcp-smoke.json` when it passes. The scheduler gates this arm on that successful test.

## Shared task conditions

- Dataset: Parametric CAD Bench V3, only its image-to-CAD tasks.
- Examples: `freecad-f32bdb2966`, `freecad-6b54209a13`, `freecad-f4e56c467a`.
- FreeCAD: **1.1.0** inside Docker.
- Harbor: **0.23.0**.
- Reasoning effort: **high** for both models and all setups.
- Per-attempt time limit: **9,000 seconds**.
- Output: `/app/answer.py` and `/app/answer.FCStd`.
- Exactly one editable PartDesign Body producing one solid; a baked `Part::Feature` is not accepted.
- Original task-specific engineering drawing is the only geometry source.
- Official hidden verifier remains separate and unchanged.
- Temporary provider usage limits are automatically rescheduled in separate attempts; previous logs/results remain intact. This operational rescheduling is disclosed rather than silently replacing failed attempts.

## Excluded

- **Fable 5.1 and Fable 5:** both require usage credits on the current Claude Pro subscription. Excluded after the user's instruction; no Fable CAD trials launched.
- **Gemini:** excluded at the user's request.
- **Pi/OpenCode:** not included; the user clarified that the experiment concerns added skills/tools rather than switching coding CLIs.
- **Entire Superpowers framework, other CAD skills, combined skill+tool setups:** not part of this initial pilot.

The popularity/source evidence for selecting the skill and tool is in [research/selection.md](research/selection.md). Popularity selects candidates; it does not establish that they improve CAD accuracy.

## Configuration, results, and logs

- [configs/experiment.json](configs/experiment.json): model, agent, source versions, and task settings.
- [configs/exclusions.json](configs/exclusions.json): explicit exclusions.
- [configs/cohort.lock.json](configs/cohort.lock.json): frozen examples and file hashes.
- [configs/enhancements.lock.json](configs/enhancements.lock.json): skill/tool file hashes.
- [reports/pilot-3-v1/results.json](reports/pilot-3-v1/results.json): latest collected trial results.
- [reports/pilot-3-v1/index.html](reports/pilot-3-v1/index.html): generated stories.
- `jobs/`: complete native logs, trajectories, submitted CAD/Python, and verifier diagnostics.
- `runs/pilot-3-v1/queue-state.json`: automatic self-loop state and rescheduling history.

This file describes the configured matrix. It does not claim that all 18 trials have finished; consult the current results and queue state for progress.
