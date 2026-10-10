# A stepped enclosure with difficult side passages

Both agents constructed the stepped enclosure and its openings as editable PartDesign features. Sol revised the angled side throats during its run, using the drawing’s 1.9 mm roof drop and 20° slope to reposition them. That revision is an agent action in the preserved script history; no reference geometry or grader feedback was supplied to it.

Opus scored **0.615385**, compared with **0.333304** for Sol. Opus’s volume, surface area, bounding box, and principal moments all passed the grader’s matching criteria, but its surface alignment still had **1.7303 mm RMSE**. Sol’s volume differed by **2.479%**, its surface-type comparison was marked “Far,” and its surface alignment had **2.2983 mm RMSE**. A close overall size did not guarantee that the internal and side geometry matched.

The specification checker found **22 of 24 checks** consistent for Opus and **21 of 24** for Sol; the remaining checks were not found, rather than reported inconsistent. The full diagnostics below preserve that distinction. The three browser panels let you inspect the openings directly; these scores alone do not identify every misplaced surface.
