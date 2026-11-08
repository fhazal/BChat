# BChat guide

How to do things in BChat, the calm IRC client for Windows by BajuBesi Labs. Every answer below matches what BChat really does. Menu paths are written like **Settings → Preferences → Colors**.

New to IRC? Start with [Getting started](#getting-started). Something not working? Jump to [When something goes wrong](#when-something-goes-wrong).

---

## Getting started

### What is IRC?
IRC is one of the oldest ways to chat on the internet. You join a **network** (a group of servers, like Libera.Chat or BajuBesi Community), then **channels** on it (rooms whose names start with `#`, like `#BChat`). You pick a **nickname**. No account or phone number is needed.

### What happens the first time I open BChat?
If BChat finds no networks, it shows the **Welcome** window: type a nickname, pick where to start, and click **Connect**.
- **BajuBesi Community** (recommended) connects to irc.bajubesi.org and joins **#BChat** (help and chat about BChat) and **#chat**.
- **Libera.Chat** and **OFTC** are big open-source networks. After you connect, BChat asks which channel to join.
- **I'll Set Up My Own...** opens the Network List instead.

The Welcome window appears only once. If you used XChat 2 or XChat-SE before, BChat imports your networks and nick instead and skips it.

### How do I connect to a network?
Open **BChat → Network List** (`Ctrl+S`), pick a network, and click **Connect**. To have it connect every time BChat starts, select it, click **Edit...** and tick **Auto connect to this network at startup**.

### How do I add a network that isn't in the list?
In the Network List, click **Add**, give it a name, then **Edit...** and type its servers, one per line, as `host/port`. Use `/+port` for an encrypted (SSL) port, for example `irc.bajubesi.org/+6697`.

You can also type `/server irc.example.org +6697` in any tab. To keep that server, right-click it in the tree and choose **Add Network**.

### How do I join a channel?
Type `/join #channelname` and press Enter, or use **Server → Join a Channel...**. To see every channel on a network, use **Server → List of Channels...** (or `/list`).

To join channels automatically on connect, open **Edit...** for the network in the Network List and fill in **Auto-join channels:** (for example `#BChat,#chat`).

### How do I leave a channel?
Right-click the channel in the list on the left (or its tab) and choose **Leave Channel**, or type `/part` in that channel.

### How do I change my nickname?
Type `/nick NewName`. To change it for good, open the Network List and change **Nick name:** under **User Information**, or per network in **Edit...** (untick **Use global user information** first).

---

## Chatting

### What are the most useful commands?
- `/join #channel`: join a channel
- `/part`: leave the channel you're in
- `/hop`: leave and rejoin the channel you're in (`/cycle` does the same)
- `/msg nick text`: send a private message
- `/query nick`: open a private tab with someone
- `/me waves`: say what you're doing (shows as an action)
- `/nick NewName`: change your nickname
- `/away reason` and `/back`: mark yourself away and back
- `/whois nick`: see who someone is
- `/topic`: show the channel topic
- `/help`: every command, with a search box (also **Help → Contents**, `F1`)

### How do I switch between tabs?
Click a channel in the tree on the left, or use `Alt+1` to `Alt+9`, or `Ctrl+PageUp` / `Ctrl+PageDown`. **View → Channel Switcher** chooses between the tree and tabs.

### How do I use colours, bold and underline?
In the input box: `Ctrl+B` bold, `Ctrl+U` underline, `Ctrl+Shift+I` italic, `Ctrl+R` reverse, `Ctrl+E` strikethrough, `Ctrl+K` colour, `Ctrl+O` back to normal. Select some text first and `Ctrl+B`, `Ctrl+U`, `Ctrl+Shift+I`, `Ctrl+R` or `Ctrl+E` formats just that part. The topic bar has **B**, **U**, **I**, **Fg** and **Bg** buttons when you're allowed to change the topic.

### Why can't I change the topic?
Many channels only let operators (people with **@**) change the topic. When you can't, BChat hides the topic buttons.

### How do I open a private chat with someone?
Right-click their name in the nick list and choose **Open Dialog Window**, or type `/query nick`. Double-clicking a name shows who they are (whois). The right-click menu also has **Send a File**, **User Info (WhoIs)** and **Add to Friends List**.

### How do I find something someone said earlier?
**Window → Search Text...** (`Ctrl+F`) searches the tab you're in. `/lastlog word` lists every line with that word.

### What is the line across the chat?
It's the **marker line**. It shows where you stopped reading when you left that tab. **Window → Reset Marker Line** (`Ctrl+M`) moves it. To hide it, untick **Show marker line** in **Settings → Preferences → Text box**.

### How do I ignore someone?
Type `/ignore nick`. **Window → Ignore List...** shows your ignores and removes them (`/unignore nick` works too).

### How do I keep logs of my chats?
**Settings → Preferences → Logging**, tick **Enable logging of conversations to disk**. For a single tab, right-click it and choose **Log to Disk**. Logs go to `%APPDATA%\BChat\logs`.

---

## Notifications and the tray

### How does BChat tell me about new messages?
When BChat isn't the window you're using, a small card appears above the taskbar for **private messages** and when someone **mentions your nick**. Click the card to jump to that chat. The tray icon blinks too.

### Can I stop the notification cards?
Yes: **Settings → Preferences → Alerts**, in the row **Show pop-up notifications on:**, untick what you don't want (channel messages, private messages, highlights).

### Will cards pop up while I'm gaming?
No. BChat stays quiet while Windows says you're busy: full-screen games, presentations, and Focus / Do Not Disturb. Messages still make the tray icon blink.

### What if many messages arrive at once?
BChat never floods your screen. Messages from the same person update one card, at most three cards show, and anything more becomes one summary card ("N more messages from M people").

### How do I keep BChat running in the tray?
**Settings → Preferences → General**, tick **Minimize button sends BChat to the tray** and/or **Close button sends BChat to the tray**. To really quit, right-click the tray icon → **Quit**, or use **BChat → Quit** (`Ctrl+Q`).

### Can BChat start with Windows?
Yes: **Settings → Preferences → General → Start with Windows**. Tick **Start minimized** too if you want it to start quietly.

---

## Looks and themes

### How do I change the theme?
**Settings → Preferences → Colors**, pick one from the **Theme:** list, and click **OK**. Dark themes: **Catppuccin Mocha** (the default), **Macchiato**, **Frappé**, **One Dark Pro** and **Dracula**. Light theme: **Catppuccin Latte**.

### How do I switch to a light theme?
**Settings → Preferences → Colors**, choose **Theme: Catppuccin Latte**, and click **OK**.

### Which themes are there?
Catppuccin **Mocha** (the default), **Macchiato**, **Frappé** and **Latte**, plus **One Dark Pro** and **Dracula**.

### Can I change single colours?
Yes. In **Settings → Preferences → Colors**, click any colour to change it. The theme then shows as "Custom (based on ...)". **Reset to Theme** puts it back.

### How do I change the chat font?
**Settings → Preferences → Text box**.

---

## Safety and privacy

### Where does BChat keep my passwords?
In **Windows Credential Manager**, not in a settings file. That covers server, SASL, NickServ and proxy passwords. Your settings file (`%APPDATA%\BChat\config.json`) holds no passwords.

### BChat asked me to check a server's certificate. What should I do?
BChat checks every encrypted server's certificate. If it can't be verified (often a small network that made its own certificate), BChat shows its details and asks:
- **Don't Connect**: the safe choice if you didn't expect this
- **Connect Once**: just this time
- **Always Trust**: remember this exact certificate for this network

If a certificate you trusted ever changes, BChat warns you again, because that's also what it looks like when someone listens in. When unsure, ask the network first.

### Why did BChat ask before opening a link?
BChat asks first only for **risky links**: links that download a program (like `.exe`), look-alike web addresses, bare IP addresses, and similar tricks. It shows who posted the link and where it leads. **Cancel** is the default. Normal links open with one click.

### What happens when I click an irc:// link?
BChat asks first and never joins on its own. The question shows the channel, the network and whether the connection is encrypted (green shield) or not (orange shield). On a network you're already on, Join opens the channel in a new tab. On a new network, BChat adds it to your Network List, opens its own server tab, connects with your nick and then joins. The installer can also make your browser open irc:// and ircs:// links in BChat.

### Can I see what was said before I joined?
Yes, on networks that keep channel history (IRCv3 chathistory, for example UnrealIRCd channels with mode +H). When you join, BChat shows the last messages above your join line, under a grey line that says so. After a reconnect it only fetches what you missed. Old lines never make a sound or pop up a card.

### Does BChat track me or show ads?
No. BChat has no ads, no accounts and no tracking. It connects only to the IRC networks you choose, and to GitHub once a day to look for updates (you can turn that off). Like any IRC client, the networks you join can see your IP address.

---

## Files and direct chats (DCC)

### How do I send someone a file?
Right-click their name → **Send a File**, or type `/dcc send nick`. **Window → File Transfers...** shows every transfer.

### How do I receive a file?
When someone offers a file, it appears in **Window → File Transfers...**. Select it and click **Accept**. Files go to the folder set in **Settings → Preferences → File transfers → Download files to:** (by default `%APPDATA%\BChat\downloads`).

### Why does BChat warn me about some files?
Programs (`.exe`, `.msi`, scripts and similar) can harm your PC, so BChat asks **Accept this file?** first, and never accepts them by itself. Hidden tricks that disguise a program as a picture are removed from the file name. Received files are marked as coming from the internet, so Windows checks them before they run.

### My antivirus blocked BChat after I received a program. Why?
Some antivirus programs (Bitdefender, for example) treat "a new app received a program over the internet" as suspicious, even when the app is BChat. See [antivirus](#my-antivirus-blocked-or-removed-bchat) below. If you only want to see the warning, click **Cancel** at **Accept this file?**: nothing is downloaded then.

---

## Updates

### How does BChat update?
**Settings → Preferences → BChat → Updates** shows your version and whether a new one is out. When one is available, an **Update** entry also appears after **Help** in the menu bar, and **Help → About** says so next to the version. Click **Download**: BChat checks the file's signature and installs it when you quit, or right away with **Install Now**. Your settings, networks and logs stay.

### Is an update safe?
Every update is signed by BajuBesi Labs. BChat checks the signature and the file's checksum, and throws away anything that doesn't match.

### Can I try test versions?
Yes: tick **Include test versions** on the Updates page.

---

## Plugins and scripts

### Can I add scripts to BChat?
Yes. BChat runs Python plugins written for XChat's Python interface, so most XChat 2 scripts work. Load one with **BChat → Load Plugin or Script...**, or put it in `%APPDATA%\BChat\addons` to load it at start. **Window → Plugins and Scripts...** lists them. Only load plugins you trust: a plugin can do anything BChat can.

---

## When something goes wrong

### BChat won't connect to anything
- Check that your internet works in a browser.
- **Antivirus or firewall:** if BChat ever triggered an alert, your antivirus may now block its internet access. In Bitdefender: **Protection → Firewall → Rules**, find **BChat.exe**, and set it to allow.
- Look at the server tab (the network's name in the tree): its last lines say what went wrong.

### It says my nickname is already in use
Someone else has it. BChat tries your **Second choice** and **Third choice** nicknames from the Network List. You can also type `/nick AnotherName`.

### A network says I must identify or log in
If you registered your nick with NickServ, put the password in the network's **Edit...** window, as **NickServ password:** or **SASL account:** and **SASL password:**. BChat sends it each time you connect, and keeps it in Windows Credential Manager.

### Windows says "Windows protected your PC" when I install
The installer isn't code-signed yet, so SmartScreen warns about it. Choose **More info → Run anyway**.

### My antivirus blocked or removed BChat
BChat isn't code-signed yet, and some antivirus programs distrust unsigned apps.
1. Restore every BChat item from the antivirus quarantine (in Bitdefender: **Protection → Antivirus → Manage quarantine**). That includes `config.json`, which holds your settings.
2. Restart Windows if the antivirus asks to.
3. If BChat still won't connect, allow **BChat.exe** in the antivirus firewall rules.
4. If BChat doesn't start at all, run the installer again over the top. Your settings stay.

### I don't get notification cards
Check **Settings → Preferences → Alerts → Show pop-up notifications on:**. Also check that Windows Focus / Do Not Disturb is off, and that you're not in a full-screen game: BChat stays quiet then on purpose.

### Where are my settings, logs and downloads?
In `%APPDATA%\BChat`: `config.json` (settings and networks, no passwords), `logs\`, `scrollback\`, `addons\` (plugins), `downloads\` (files received over DCC). Passwords are in Windows Credential Manager under entries named `BChat:...`.

### How do I report a bug or ask for help?
Ask in **#BChat** on irc.bajubesi.org: people there and the Buzz helper bot can help. You can also open an issue on [GitHub](https://github.com/fhazal/BChat/issues). **Help → About** lists your BChat, Windows and Qt versions; you can select and copy them for a bug report.
