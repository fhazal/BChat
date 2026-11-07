# BChat

A dark IRC client for Windows in the classic XChat 2 style, by BajuBesi Labs.

- Network tree, topic bar, chat with a nick column, and a nick list with status lights
- SSL and ZNC servers, with auto-connect and auto-join
- Imports your network list and nick from XChat 2 and XChat-SE
- macOS-style window buttons and the Catppuccin Mocha colour theme

## Run from source

```bash
python -m pip install PySide6
python -m bchat
```

Settings are stored in `%APPDATA%\BChat`. Network, SASL, NickServ and proxy passwords are kept in Windows Credential Manager, not in that folder.

## Tests

```bash
python -m pip install pytest
python -m pytest
```

## Licence

GPL-2.0-or-later, see `LICENSE`. Menu, button and chat icons are [Lucide](https://lucide.dev) (ISC), coloured from the theme. The BChat logo and the user list lights are BChat's own, the lights drawn by `packaging/make_lights.py` and every logo file (icon, title bar, installer pictures) built from the user's transparent set by `packaging/make_logo_assets.py`. Themes: [Catppuccin](https://catppuccin.com), [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) and [Dracula](https://draculatheme.com), all MIT.

## Support BChat

BChat is free and has no ads. If it makes IRC better for you, you can support its development:

[![Support BChat on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bajubesi)

