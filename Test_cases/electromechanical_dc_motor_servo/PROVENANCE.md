# Provenance: electromechanical_dc_motor_servo

Retrieval date for all files: **2026-09-25**.

## How the CTMS files were obtained

The live CTMS site (`ctms.engin.umich.edu`) returns HTTP 403 and a Cloudflare
"Just a moment..." JavaScript challenge to curl, including with a browser User-Agent
and Accept headers. So the CTMS pages and figures were fetched from **Internet
Archive Wayback Machine** snapshots of the same URLs. I used the raw `id_` form, so
the bytes are the archived originals with no Wayback toolbar or URL rewriting. The
snapshot timestamps are listed per file below. Every CTMS page has this footer: "All
contents licensed under a Creative Commons Attribution-ShareAlike 4.0 International
License." The figures are part of those contents, so the same licence covers them.

Attribution: *Control Tutorials for MATLAB and Simulink* (CTMS). The site header
carries University of Michigan, Carnegie Mellon University and University of Detroit
Mercy logos. Licence: CC BY-SA 4.0. The task brief expected this material to be
copyrighted with no licence. In fact the site states CC BY-SA 4.0, so these files
may be redistributed with attribution under the same licence.

## Files

### sources/01_ctms_dc_motor_speed_system_modeling.md
- Original URL: https://ctms.engin.umich.edu/CTMS/index.php?example=MotorSpeed&section=SystemModeling
- Fetched from: http://web.archive.org/web/20260225141934id_/https://ctms.engin.umich.edu/CTMS/index.php?example=MotorSpeed&section=SystemModeling
- Original format: HTML. Converted to Markdown (.md) because .html is not a supported input format.
- Licence: CC BY-SA 4.0 (stated on the page).
- Changes:
  - Kept only the article body (`div.content_fx`) and the page's licence line.
  - Removed the site navigation, the tab bar, the "Related Tutorial Links" and "Related External Links" boxes, the section-nav footer, and the hidden HTML comment that holds the MATLAB source.
  - The page renders equations as images, and each image has LaTeX alt text written by the page author. Each equation image was replaced by that alt text, verbatim (for example `$$  T = K_{t} i$$`).
  - The figure image (`motor.png`) was replaced by a Markdown image reference to its original URL, with empty alt text as on the page. The figure itself is file 02.
  - Hyperlinks were reduced to their link text. `<tt>` became backticks, `<b>`/`<i>` became `**`/`*`, and `<pre>` blocks became fenced code blocks. Whitespace was normalised.
  - Sentences, numbers, units, equations and MATLAB code and output were not changed. A script checked that every number in the .md appears in the source HTML.

### sources/02_ctms_dc_motor_armature_rotor_figure.png
- Original URL: https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/System/Modeling/figures/motor.png
- Fetched from: http://web.archive.org/web/20260225141935id_/https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/System/Modeling/figures/motor.png
- Licence: CC BY-SA 4.0 (part of the CTMS page contents).
- Changes: none (byte-identical; 413x270 PNG). This is the armature equivalent circuit and rotor free-body diagram that file 01 refers to.

### sources/03_ctms_dc_motor_speed_pid_controller_design.md
- Original URL: https://ctms.engin.umich.edu/CTMS/index.php?example=MotorSpeed&section=ControlPID
- Fetched from: http://web.archive.org/web/20251104183813id_/https://ctms.engin.umich.edu/CTMS/index.php?example=MotorSpeed&section=ControlPID
- Original format: HTML. Converted to Markdown.
- Licence: CC BY-SA 4.0 (stated on the page).
- Changes: the same conversion as file 01, done by the same script. The figures on this page are Markdown image references to their original URLs. Only two of them are included in the packet: the loop block diagram (file 04) and the final step-response plot (file 05). The P-only plot, the two Control System Designer screenshots and the other two step-response plots are referenced but not included.

### sources/04_ctms_speed_loop_block_diagram.png
- Original URL: https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/Control/PID/figures/feedback_motors.png
- Fetched from: http://web.archive.org/web/20251104183815id_/https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/Control/PID/figures/feedback_motors.png
- Licence: CC BY-SA 4.0.
- Changes: none (byte-identical; 482x227 PNG). This is the unity-feedback block diagram r -> (+/-) -> e -> C(s) -> u -> P(s) -> theta-dot.

### sources/05_ctms_pid_large_ki_large_kd_step_response.png
- Original URL: https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/Control/PID/figures/sPID_control_04.png
- Fetched from: http://web.archive.org/web/20250802052527id_/https://ctms.engin.umich.edu/CTMS/Content/MotorSpeed/Control/PID/figures/sPID_control_04.png
- Licence: CC BY-SA 4.0.
- Changes: none (byte-identical; 550x525 PNG). This is a MATLAB figure titled "PID Control with Large Ki and Large Kd". It is annotated with peak amplitude 1.01, overshoot 1.03 %, time of peak 0.59 s, settling time 0.257 s, and final value 1.

### sources/06_maxon_amax22_5W_motor_datasheet.pdf
- Original URL: https://www.farnell.com/datasheets/55280.pdf (distributor-hosted copy of a maxon catalogue page)
- Fetched directly with curl (HTTP 200, application/pdf, 78,896 bytes).
- Content: maxon motor catalogue page "maxon DC motor 105", "April 2000 edition / subject to change". It covers the A-max 22, Ø22 mm, precious-metal brushes, CLL, 5 W motor, with 12 winding variants (order numbers 110117 to 110129) and 21 motor-data lines, including terminal resistance, terminal inductance, torque constant, speed constant, mechanical time constant and rotor inertia.
- Licence: copyright maxon motor. The file is freely downloadable with no login but has no open licence. **Internal testing only, do not redistribute.**
- Changes: none (the original PDF, byte-identical).
- Note: the PDF's text layer is badly ordered when extracted with `pdftotext -layout`, because row labels and value rows are offset from each other. `pdftotext -raw` keeps them aligned. The file was deliberately left as it is, because messy PDF extraction is part of what this packet tests.

## Sources considered but not used
- Live CTMS pages: Cloudflare challenge (see above). The Wayback copies were used instead.
- maxon's own site (`maxongroup.com/medias/sys_master/8798985748510.pdf`): HTTP 403 to curl.
- `blog.jsumo.com/.../maxon-dc-motor-pdf-2332.pdf` (a maxon "special program" sheet, May 2007): reachable, but it is hosted on a third-party blog. The distributor copy of the A-max 22 page was preferred.
- WebSearch was used only to discover the datasheet URL. No WebFetch output was used for any file.
