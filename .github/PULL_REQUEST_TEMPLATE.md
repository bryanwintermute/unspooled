<!--
Thanks for the PR! A few quick checks before submitting.
Delete sections that don't apply.
-->

## What does this PR do?

<!-- One-paragraph summary. -->

## Type of change

- [ ] Bug fix on RP332 (the tested SKU)
- [ ] New SKU support (adds tests + README entry)
- [ ] New command / setting recovered from PrinterTool.exe
- [ ] Documentation
- [ ] CI / tests / tooling
- [ ] Other:

## Testing

<!-- Required for code changes. Choose what applies. -->

- [ ] `python3 -m pytest tests/` passes locally
- [ ] Ran the changed command(s) on real hardware: model __________, firmware __________
- [ ] Captured bytes match Wine reference (paste in the PR description if new)
- [ ] No real hardware was harmed (or, if NV-RAM was changed, it was restored)

## Wire-protocol changes (if any)

<!--
If you're adding a new command or modifying an existing one, paste
the captured bytes from PrinterTool.exe AND from this CLI's
--dry-run side by side. They should match exactly.
-->

```
PrinterTool.exe capture: ...
This CLI's --dry-run:    ...
```

## Anything weird I should know?

<!--
Footguns, vendor quirks, untested edge cases. Keep the next
maintainer (or future you) sane.
-->
