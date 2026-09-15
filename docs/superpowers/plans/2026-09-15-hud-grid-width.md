# Desktop HUD grid width repair

Base 64f38aa0687516ea0c7595f2d3e10f999f8acc28. Formal plan before implementation, 2026-09-15.

Independent browser audit reproduced document width1299 at viewport1280 on the existing main bundle. The cockpit grid and its flex wrapper retain automatic intrinsic minimums; the outer 1fr track grows beyond the shell. A1440-only test hides the defect. This unit repairs sizing within the existing HUD grid without changing routing, breakpoints, authority or hiding overflow.

1. Add actual production-bundle Playwright regression at1101,1280,1440 pixels for cockpit and console gallery routes; verify document and workzone stay inside viewport and right column remains reachable. Use existing isolated routing fixture and preserve its navigation smoke.
2. Observe failures before CSS change. Apply minimum-width/zero-minimum fractional tracks only to existing main/workzone layout selectors, preserving fixed rail and side column widths and <=1100 stacking.
3. Rebuild and rerun width and existing desktop/mobile route checks, inspect screenshot and edge geometry; run TypeScript and frontend checks. Independent review before integration. No hidden-overflow workaround, protected files or backend behavior changes. Source count delta is browser-only.

## Observed verification

Initial production-bundle regression failed at1101/1280 and passed at1440 (`/tmp/nerva-grid-width-red.log`). Zero-minimum main/workzone tracks repaired document width, but screenshot inspection exposed the input bar painting across the neighboring column. Added real control bounding-box and minimum usable text-input checks; both narrower cases failed again (`/tmp/nerva-grid-composer-red.log`). Cockpit-only flexible wrapping and zero-minimum input sizing now preserve all controls within the column without hiding content.

Rebuilt final bundle passed five browser cases: three width/column/composer checks plus existing desktop and Pixel7 routing/history/focus/lazy-load smoke (`/tmp/nerva-grid-width-final.log`). Three duplicate desktop-width cases are deliberately skipped in the mobile project. Both frontend TypeScript programs pass. Root inspected the1101 screenshot: attach/channel controls wrap above the text/voice/send row; the right context column remains fully visible. Backend and unit-test counts are unchanged; these are three browser regressions. Independent review and final integration remain pending.

## Integration with cloud Images

The same source was independently cleared: five route/desktop checks and three additional393/800/1000 stacked control-bound/focus/reachability checks pass. Root integrated source with cloud Images and script workdir, regenerated conflicted assets from source, and repeated all five route/desktop checks successfully. The cloud workflow desktop fixture is restored from1440 to1280 so its full approval→PNG→gallery path will exercise the repaired width rather than avoid it.

The full cloud approval→PNG→gallery→ZIP browser workflow now passes at1280px and Pixel7 against the integrated bundle (`/tmp/nerva-grid-cloud-1280-browser.log`,2 passed). It uses actual isolated routes/signed worker with mocked provider transport; no paid generation.
