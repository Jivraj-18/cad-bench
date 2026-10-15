# One drawing, two readings of the fork opening

Sol built the rear plate, fork-and-stem profile, bearing boss, pin bore, and mounting holes as five PartDesign features. It then inspected the result through FreeCAD MCP and checked that the body was one valid solid. Two distinct saved CAD geometries were captured during the run. The first used a 50.39 × 25 mm rear opening and a 46.39 × 23.13 mm forward opening. After inspecting it, Sol swapped those dimensions between the profiles. This reduced the volume from 182,010.666 to 179,209.427 mm³, but retained a step that does not exist in the reference.

The important mistake was in reading the inset lines around the fork opening. The final script treats **46.39 × 23.13 mm as a smaller opening in the rear plate**, behind the **50.39 × 25 mm forward opening**. Those smaller dimensions actually locate the shoulder-radius centers; the reference has the approximately 50.39 × 25 mm opening in both profiles. Inspection of the reference’s `Sketch001` and `Sketch002` confirms the same opening side lines at approximately ±25.1953 mm, each 25 mm tall.

That interpretation leaves extra material at the rear opening. The candidate volume is **179,209.427 mm³**, compared with **177,334.540 mm³** for the reference. The incorrect rear notch accounts for about **1,867.5 mm³** of the **1,874.9 mm³** excess. This is a geometry error even though the script contains the drawing’s labeled numbers.

The specification checker accepted **30 of 30 checks**, but geometry scored **0.310054**, producing an overall score of **0.473345**. The official face-center alignment diagnostic reports **3.0414 mm RMSE**. Passing the named-dimension checks did not establish that the part matched the reference.

[Reference opening measurements](evidence/freecad-f32bdb2966/codex-sol-6-1--freecad-mcp/reference-opening-inspection.json) support this diagnosis. The CAD comparison below shows the result; the diagnostic details preserve the official scoring evidence.

Opus reconstructed the same bracket with an overall score of **0.999873** and geometry score of **0.999746**. All **30 specification checks** passed, and the official face-center ICP RMSE was **0.000210 mm**. It is the closest reconstruction in this pilot, while Sol’s extra step at the rear opening remains a geometric mismatch.

**What this means for an engineering drawing:** a visually convincing draft can still contain a functional opening error. Here all named specification checks passed even though Codex left an extra step at the rear opening. Inspect the material-difference view from the back before accepting the part; passing the checker alone is insufficient.
