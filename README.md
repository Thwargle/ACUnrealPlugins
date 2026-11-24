# AC:Unreal Plugins

Players can open **Plugin Manager** on the AC:Unreal account screen, browse releases, install or update a plugin, and enable it under **Installed**. The client checks each download against the SHA-256 digest in [catalog.xml](catalog.xml).

## Register a plugin

1. Publish your API 1 or 2 Lua plugin in a public GitHub repository. Give it a stable lowercase ID in `plugin.json`. Keep the manifest, `main.lua`, optional `default.json`, `images/*.png` and `sounds/*.wav` together.
2. Run `python tools/package.py PATH_TO_PLUGIN --output dist` with Python 3.10 or later. Upload `dist/YOUR_ID.acplugin` as an asset of a published stable GitHub release. The release tag appears in the client. Use an ordinary tag such as `v1.2.0`.
3. Open a pull request adding `registry/YOUR_ID.xml`. Use [the Graphics Gallery entry](registry/graphics_gallery.xml) as a template. Enter your repository as `owner/repository`. An optional PNG logo lives beside the registration with the same ID, up to 256 × 256 pixels and 64 KiB. Omit the logo element to use the client's default icon.
4. A maintainer reviews the initial registration. For later versions, publish a new stable release in **your own repo** with the same asset filename. The hourly workflow updates the download link and checksum. Players choose when to update. No catalog pull request is needed for ordinary releases.

The catalog retains the previous release when an existing publisher is temporarily unavailable. To delist a plugin, remove its registration by pull request. A delisted plugin can still be removed in the client. Ownership transfers and changes to the registered repository require review.

Run `python tools/catalog.py --check` to validate registrations against live releases. Maintainers can also run **Refresh plugin catalog** manually in Actions. Treat submitted plugins as third-party software and review the source and requested permissions before enabling them.

[AC:Unreal public plugin API](https://github.com/Thwargle/ACE/blob/master/Unreal/Plugins/ACEClient/Docs/Plugins/PublicAPI.md) · [Graphics Gallery example source](examples/graphics_gallery)

