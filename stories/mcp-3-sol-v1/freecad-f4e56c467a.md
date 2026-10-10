# Similar bulk geometry, different surface matches

This double-clevis mount combines a 20 mm base, raised 3 mm slot rims, two 25 mm ears separated by 30 mm, a Ø25 cross bore, and vertical Ø8 blind holes. Sol recorded a tension between the labeled flank angles and perfect circle tangency, and chose to honor the angles while joining the lines to the circle intersections. That is its stated modeling choice, preserved in its script and tool history.

Both outputs passed **32 of 32 specification checks**. Sol scored **0.710356**, ahead of Opus at **0.663475** on this drawing. Their volume differences were only **0.061%** and **0.105%**, respectively, but the official face-center ICP RMSE was **0.66994 mm** for Sol and **2.3833 mm** for Opus. Nearly equal volumes conceal differences in where the material lies.

The browser comparison and saved revisions expose the actual geometry. The aggregate diagnostics establish that Sol matched better on this example; they do not, by themselves, prove which particular feature caused every residual. Neither output received a perfect official score.

Exact solid overlap is **99.88194% for Opus** and **99.93171% for Sol** under the documented finite rigid pose search. Both are geometrically close. Their lower official scores include topology-dependent face-center penalties; those penalties should not be interpreted as equally large physical shape errors.
