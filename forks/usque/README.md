# usque — swg-panel build

The MASQUE client (`Diniboy1123/usque`) that a **`warp-masque` exit** runs as `usque nativetun`: WARP carried over
HTTP/3 (or HTTP/2) instead of WireGuard, presented to the node as a TUN device. **Unmodified** upstream; we build it at a
pinned commit so every node runs bytes it can check. Status: the pin exists; nothing on a node uses it yet.

## Build

```bash
./build.sh [output]          # clones upstream@pin, builds a static binary (needs go1.27.1 exactly)
GOARCH=arm64 ./build.sh      # cross-build (amd64 / arm64)
```

- Pinned upstream: **`6aa03fc9`** (`6aa03fc97d12848dce34eedbd187fb1077b5d1ea`, 2026-07-20). Upstream has no tags.
- Toolchain **go1.27.1**, `CGO_ENABLED=0 go build -trimpath -ldflags="-s -w"`, `-buildvcs=false`. The script refuses any
  other Go: the sha256 only reproduces with this one.
- Release tag `usque-20260720-6aa03fc` (`-2`, `-3`… on a rebuild of the same commit), assets `usque-linux-amd64` /
  `usque-linux-arm64`.

| arch | sha256 |
|---|---|
| amd64 | `51ea456fbf9f211f7be96d0a609eb985c16baebd4035461f4ab0177a6aeea032` |
| arm64 | `709aaeefcd2320f65b03440aaaf389514dd9140749bda1234cf117c117183797` |

These are `USQ_SHA256` in `swg-noded`. The node will refuse any other bytes, from every source. The CI workflow
`fork-binaries` (fork `usque`) rebuilds them and fails unless both arches match. arm64 is built but has never been run.

## Licence

usque is MIT-licensed. Its notice is in [`LICENSE.md`](LICENSE.md), and every release of this build carries it.
