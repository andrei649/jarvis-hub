# H595 product interruption checkpoint

Local code/ingress integration is verified; H595 and H660 remain partial.
The source manifest and report identify final tested scope and the last taint
correction. Composition passed 297 cases; the final affected run passed 109.
Counts overlap and are not additive. Docker/live provider acceptance is absent.

Rollback: exact batch preimages are outside the repository in
`/tmp/nerva-h595-interrupt-baseline-20261005`; preserve inherited edits.
