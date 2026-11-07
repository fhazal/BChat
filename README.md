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

Settings are stored in `%APPDATA%\BChat`. Network passwords are saved there as plain text, the same way XChat stores them.

## Tests

```bash
python -m pip install pytest
python -m pytest
```

## Licence

GPL-2.0-or-later, see `LICENSE`. Menu, chat and dialog icons come from XChat 2 and its GTK build, both GPL/LGPL. The BChat logo and the user list lights are BChat's own, the lights drawn by `packaging/make_lights.py` and every logo file (icon, title bar, installer pictures) built from the user's transparent set by `packaging/make_logo_assets.py`. Colours are [Catppuccin Mocha](https://catppuccin.com) (MIT).
