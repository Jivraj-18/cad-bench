# Enhancement selection, 8 October 2026

The user uses “harness” to mean additions such as skills and tools that improve an agent. Different CLIs alone are not the main experimental question. Models are compared in their native agents; each enhancement is then compared to that same model/agent baseline on identical drawings.

## Selected skill: verification-before-completion

- Source: [obra/superpowers](https://github.com/obra/superpowers), MIT license.
- Frozen commit: `8ca22dba9a94f28898bbce59f2537ff4d87c747d`.
- [Skill listing](https://www.skills.sh/obra/superpowers/verification-before-completion): approximately 230.2K installs when checked.
- GitHub API: 296,594 repository stars when checked. Repository-level popularity is not proof that this particular skill improves CAD.
- Multiple discussions include [a positive workflow report](https://www.reddit.com/r/ClaudeCode/comments/1r9y2ka/claude_codes_superpowers_plugin_actually_delivers/), [whether people still use it](https://www.reddit.com/r/ClaudeCode/comments/1u2tqud/are_you_guys_still_using_the_superpowers_skill/), and [a removal/criticism report](https://www.reddit.com/r/ClaudeCode/comments/1upt8mr/why_i_removed_superpowers_from_claude/).

The hypothesis is narrower than the framework's marketing: forcing fresh evidence before declaring completion might lead an agent to discover geometric mistakes. It cannot supply hidden reference geometry, and checking only a valid solid/bounding box can still miss the true error. The experiment installs **only this skill**, not Superpowers' brainstorming/interview, parallel-agent, or TDD workflows. Explicit invocation is part of the skill arm and is disclosed; the baseline instruction is otherwise unaltered.

## Selected tool: FreeCAD MCP

- Source: [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp), MIT license.
- Frozen commit: `4751f953636f46b825424320c2f76e11159dd8c0`, package version 0.1.26.
- GitHub API: 2,741 stars and 335 forks when checked.
- A directly linked [Linux/Pi/FreeCAD workflow](https://www.reddit.com/r/LocalLLaMA/comments/1w9r73k/9_easy_steps_for_llamacpp_a_local_model_freecad/) had approximately 171–172 votes and 42 comments.
- Broader discussion appears in [FreeCAD/Claude integration](https://www.reddit.com/r/FreeCAD/comments/1mp7itt/claude_code_freecad_mcp_integration_surprisingly/) (a different MCP implementation, explicitly compared against neka-nat's), [a robotics workflow](https://www.reddit.com/r/robotics/comments/1wrfpz8/has_anyone_here_been_using_codex_or_claude_to/), and [FreeCAD MCP on r/mcp](https://www.reddit.com/r/mcp/comments/1jcl6vp/freecad_mcp_a_freecad_addon_that_implements_the/).

The hypothesis is that live document inspection and visual feedback could improve mapping between drawing callouts and constructed features. Discussion covers several implementations, so it does **not** establish that this particular source is superior. This one is selected for its maintained, inspectable implementation and stronger adoption evidence than alternatives. Actual benefit remains unmeasured until paired trials finish.

The server and FreeCAD GUI run inside the isolated task container using Xvfb. They never connect to the user's desktop. The adapter excludes prebuilt-part/library tools and unrelated FEM tools. No hidden reference or specification is exposed. Docker dependencies and the source commit are frozen and recorded. The task's official verifier is unchanged. Startup/access failures count as failures rather than silently switching to baseline tools.

## Not selected for the initial pilot

- FreeCAD-specific skill catalog: `github/awesome-copilot@freecad-scripts` showed about 1.2K installs; other CAD skills showed roughly 589, 52, 9, 8, and 5. This is interesting, but the search did not establish similarly substantial discussion of the exact skill. Respecting the user's “people are talking a lot” condition, these are deferred.
- `theosib/FreeCAD-MCP-Server`: 34 stars when checked; a useful live-state idea, but much weaker adoption evidence for this pilot.
- Pi and OpenCode: worth a future **agent implementation** comparison, but the user clarified that additions—not CLI replacements—are the main question. No Pi/OpenCode cells are included.
- Full Superpowers/GSD orchestration: popular, but adds interviews, planning, possibly multiple agents, and materially different budgets. A single verification skill makes the intervention easier to interpret.
- Geometry-aware checks authored specifically for these tasks: could contaminate the comparison if derived from hidden specifications or benchmark failures. Any future generic verification kit should be designed and frozen independently of this cohort.

Adoption observations are snapshots, not calibrated measures of effectiveness. Reddit claims are anecdotal, not controlled evidence. These sources select test candidates; official CAD Bench scores determine the outcomes.
