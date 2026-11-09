# Client and platform review

Use when changing an HTTP response, HUD, mobile, desktop, installer, archive, filesystem or OS-specific path. Read [compatibility](../../docs/COMPATIBILITY.md), [mobile parity](../../mobile/PARITY.md), and the relevant client guide.

- [ ] Compare the actual HTTP shape and auth/no-cache behavior with HUD, mobile, CLI and desktop callers. Update generated types, parity notes and the shipped HUD bundle only for changed surfaces.
- [ ] Test the supported path with the local toolchain: Python 3.12 and hash-locked environment; Node 22 with `npm ci` for HUD/mobile; Cargo.lock for desktop. Record the exact host and command.
- [ ] Exercise path separators, case differences, long absolute owner paths, UTF-8/newlines and atomic writes where relevant. Do not assume `/proc`, fork, POSIX permissions, a shell or a Windows drive on all hosts.
- [ ] Separate host/synthetic checks from Docker containment, physical device, compositor, LAN, live model/provider and release acceptance. A skipped or unavailable host check stays visible, never green by implication.

Report a platform-specific gap with the affected OS and a bounded repro. Do not remove a safety assertion just to pass on another OS.
