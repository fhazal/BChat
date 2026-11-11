# BChat guide

How to do things in BChat, the calm IRC client for Windows by BajuBesi Labs. Every answer below matches what BChat really does. Menu paths are written like **Settings → Preferences → Colors**.

New to IRC? Start with [Getting started](#getting-started). Something not working? Jump to [When something goes wrong](#when-something-goes-wrong).

---

## Getting started

### What is IRC?
IRC is one of the oldest ways to chat on the internet. You join a **network** (a group of servers, like Libera.Chat or BajuBesi Community), then **channels** on it (rooms whose names start with `#`, like `#BChat`). You pick a **nickname**. No account or phone number is needed.

### Is BChat on Mac or Linux?
No. BChat is made for **Windows 10 and 11**. There is no Mac or Linux version.

### What happens the first time I open BChat?
If BChat finds no networks, it shows the **Welcome** window: type a nickname, pick where to start, and click **Connect**.
- **BajuBesi Community** (recommended) connects to irc.bajubesi.org and joins **#BChat** (help and chat about BChat) and **#chat**.
- **Libera.Chat** is the big home of open-source communities. **Wixchat** (chat.bajubesi.org) is Malaysia's largest chat community; say hi in **#kampung**. After you connect to either, BChat asks which channel to join.
- **I'll Set Up My Own...** opens the Network List instead.

The Welcome window appears only once. If you used XChat 2 or XChat-SE before, BChat imports your networks and nick instead and skips it.

### How do I connect to a network?
Open **BChat → Network List** (`Ctrl+S`), pick a network, and click **Connect**. To have it connect every time BChat starts, select it, click **Edit...** and tick **Auto connect to this network at startup**.

### Which networks can I pick from?
**BChat → Network List** (`Ctrl+S`) has three groups: **Favourite Networks** (only once you have one), **Popular Networks** and **My Networks**. Popular Networks lists 21 well-known networks with a shield: green = encrypted and its certificate checked, amber = encrypted but BChat asks once about its certificate, grey = no encryption. Pick one and click **Connect**: BChat copies it into My Networks and connects.

### How do I mark a favourite network?
In the **Network List**, select the network and click **Favor**: it moves up into **Favourite Networks**. Click **Favor** again to move it back to My Networks. You can fold each group; BChat remembers it.

### How do I add a network that isn't in the list?
In the Network List, click **Add**, give it a name, then **Edit...** and type its servers, one per line, as `host/port`. Use `/+port` for an encrypted (SSL) port, for example `irc.bajubesi.org/+6697`.

You can also type `/server irc.example.org +6697` in any tab. To keep that server, right-click it in the tree and choose **Add Network**.


### Can a server have more than one port?
Yes. In the network's **Edit...** window, write the ports after the host with commas: `irc.example.org/+6697,7000`. BChat picks one at random and tries the next if it fails. Each server line can have its own ports.

### What are wss:// servers?
Some networks also let you in through a secure web connection. Write the server in **Edit...** as `wss://host/path` (the network tells you the address). Only secure `wss://` works; plain `ws://` is refused.

### What is STARTTLS?
A way to switch a plain port to an encrypted one after connecting. Write the port with `*` in **Edit...**, for example `irc.example.org/*6667`. If the server can't switch, BChat stops instead of carrying on unencrypted.

### Can I make BChat use only IPv4 or IPv6?
Yes: **Settings → Preferences → Network setup → Internet:** Automatic, IPv4 only or IPv6 only. On the same page, **Use IPv6 for file transfers and direct chats when you have it** lets DCC offers use IPv6 too.

### Can BChat stay offline when my VPN is off?
Yes. In **Settings → Preferences → Network setup**, type your VPN address in **Bind to:** and tick **If this address is gone (VPN off), don't connect at all**. When the VPN is off, BChat says so in the server tab and doesn't connect.

### A server gets one IRC feature wrong. Can I turn it off?
Yes, for that network only: **Edit...** → **Server features: Choose...** and untick the feature. **Back to Normal** turns them all on again. Leave them all on unless a server really misbehaves.

### Can I start BChat with a server, channel or nick?
Yes, from a shortcut or the command line: `BChat.exe -s irc.example.org/+6697 -j #channel -n MyNick`. `-s` also takes a saved network's name. These are used once and not saved.
### How do I join a channel?
Type `/join #channelname` and press Enter, or use **Server → Join a Channel...**. To see every channel on a network, use **Server → List of Channels...** (or `/list`).

To join channels automatically on connect, open **Edit...** for the network in the Network List and fill in **Auto-join channels:** (for example `#BChat,#chat`).

### How do I leave a channel?
Right-click the channel in the list on the left (or its tab) and choose **Leave Channel**, or type `/part` in that channel.

To leave every channel on a network at once, type `/partall` (you can add a reason: `/partall see you tomorrow`). The tabs stay open, like after a normal leave.

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
- `/partall`: leave every channel on this network
- `/online`: how long you've been connected to each network
- `/motd`: show the server's welcome message
- `/help`: every command, with a search box (also **Help → Contents**, `F1`)

### What does // do? Is it safe for passwords? Why did //ns identify say "No channel joined"?
Yes, in BChat 0.6.1 and newer `//` is safe for passwords: `//ns identify yourpassword`, `//oper name password` and `//whois nick` run the command the mIRC way, exactly like one slash. Nothing is said in the channel, and the raw log hides the password with stars. Older BChat (0.6.0 and before) sent a `//` line as a chat message instead: on a server tab that gave *No channel joined*, and in a channel the password would have gone to everyone, so update. To say a line that starts with `/` as chat, use `/say`, for example `/say /me is a command`.

### How do I switch between tabs?
Click a channel in the tree on the left, or use `Alt+1` to `Alt+9`, or `Ctrl+PageUp` / `Ctrl+PageDown`. **View → Channel Switcher** chooses between the tree and tabs.

### How do I write more than one line?
Press `Shift+Enter` for a new line; the input box grows to 5 lines. **Enter** sends every line. When you paste more than 5 lines, BChat first shows what will be sent and how long it takes, and lets you send it as one line instead.

### How do I reply to a message?
Right-click the message and choose **Reply**. BChat shows the message you answer above your line, and a click on it jumps to the original. **Reply** only appears on networks that support it (IRCv3 replies).

### Can people see when I'm typing?
Only if you turn it on: **Settings → Preferences → Input box**, tick **Let others see when I'm typing**. It's off at first and works only on networks that support it, never in the server tab. When someone else is typing, BChat shows "*nick* is typing…" under the chat.

### How do I use colours, bold and underline?
In the input box: `Ctrl+B` bold, `Ctrl+U` underline, `Ctrl+Shift+I` italic, `Ctrl+R` reverse, `Ctrl+E` strikethrough, `Ctrl+K` colour, `Ctrl+O` back to normal. Select some text first and `Ctrl+B`, `Ctrl+U`, `Ctrl+Shift+I`, `Ctrl+R` or `Ctrl+E` formats just that part. The topic bar has **B**, **U**, **I**, **Fg** and **Bg** buttons when you're allowed to change the topic.

### Why can't I change the topic?
Many channels only let operators (people with **@**) change the topic. When you can't, BChat hides the topic buttons.

### How do I open a private chat with someone?
Double-click their name in the nick list (like mIRC), right-click it and choose **Open Dialog Window**, or type `/query nick`. To change what a double-click does, go to Settings > Preferences > User list > Action Upon Double Click. The right-click menu also has **Send a File**, **User Info (WhoIs)** and **Add to Friends List**.

### How do I mark favourite channels?
Right-click a channel tab and choose **Favourite Channels...** (also in the **Server** menu). Tick **Join on Connect** in the tab's right-click menu to join that channel every time you connect.

### What happens when someone invites me to a channel?
A bar appears above the input box with **Join** and **Ignore**. BChat never joins by itself, and **Ignore** sends nothing.

### What is Channel Central?
Double-click in the channel's chat (like mIRC), right-click the channel tab and choose **Channel Central...**, or type `/channel`. It shows the topic, the channel modes, bans, exceptions and invites in one window. Channel operators can change them; everyone else can look.

### How do I give someone auto-op or auto-voice?
You need to be an operator (**@**) in the channel. Right-click their nick → **Operator Actions** → **ChanServ Access...** and pick **Auto-op @**, **Auto-voice +** or **No access**. BChat asks ChanServ what they have now, shows the exact line it will send, and ChanServ's answer appears in the channel. It works with Anope and Atheme services. The person must be registered with NickServ.

### Can BChat give @ or + to people by itself?
Yes, even without ChanServ: **Window → Auto-Op & Protect...**, or right-click their nick → **Operator Actions** → **Auto-Op / Auto-Voice...**. Choose them by their **NickServ account** (safest: nobody can fake it) or by their address, like `*!*@bsn.my`. A nick alone isn't allowed, because anyone can take a nick. Pick **Auto-op @** or **Auto-voice +**, and the channels (empty = every channel where you have @).

BChat only acts in channels where you have **@** yourself. It waits 2 to 4 seconds and does nothing if ChanServ or another op already did it, and it prints one grey line saying why. On channels with ChanServ, **ChanServ Access** is better, because it works while you're offline.

### What does Protect do?
Tick **Protect** on someone in **Auto-Op & Protect**: if another person takes their @ or + away, or bans them, BChat gives it back or removes the ban. It never kicks anyone, and it leaves changes by you, services and the server alone. If it keeps being taken away, BChat stops after 3 times in a minute and says so, so it can't start an op war.

### How do I find something someone said earlier?
**Window → Search Text...** (`Ctrl+F`) searches the tab you're in. `/lastlog word` lists every line with that word.

### Can I hide the server's welcome message?
Yes: **Settings → Preferences → General**, tick **Skip the server's welcome message (MOTD)** (off at first). Type `/motd` to read it any time.

### Can join and part lines be shorter?
**Settings → Preferences → Text box**, tick **Short join and part lines**. Then you see "Wira has joined" instead of "Wira (wira@host) has joined #chat". Hover a nick in the nick list to see the address. If you changed the wording yourself in Text Events, yours stays.


### Can one channel have its own settings?
Yes. Right-click the channel in the channel list and choose **Settings for #channel**: timestamps, coloured nick names, join and part lines (show, short or hide), beep, flash, pop-up cards and **Log to Disk**, for that tab only. A setting that differs from Preferences shows in bold. **Use the defaults again** clears them.

### How do I keep all the links people post?
**Window → URL Grabber...** lists every link, newest on top (new ones in bold), with who posted it, where and when. Search it, add a **Note...**, or **Send to Channel**. Tick **Keep the list after BChat closes** to keep the links (never the chat around them) and **Also catch email addresses** to collect those too.

### How do I ban someone by their account?
Type `/ban -a nick` (or `/kickban -a nick`). BChat bans their NickServ account instead of their address, so changing nick or address doesn't get them back in. It works when the network supports account bans and BChat knows the person's account.
### How long have I been online?
Type `/online`: it shows how long you've been connected to each network, and how long BChat has been running. Hovering a network in the list on the left shows it too.

### What is the line across the chat?
It's the **marker line**. It shows where you stopped reading when you left that tab. **Window → Reset Marker Line** (`Ctrl+M`) moves it. To hide it, untick **Show marker line** in **Settings → Preferences → Text box**.

### How do I ignore someone?
Right-click their nick and tick **Ignore**, or type `/ignore nick`. Untick it (or `/unignore nick`) to see them again. **Window → Ignore List...** shows all your ignores.

### How do I check someone's ping or client?
Right-click their nick and choose **CTCP → Ping**, **Time** or **Version**. The answer shows in the tab you're in.

### How do I slap someone?
Right-click their nick and choose **Slap!** (in a channel, one nick at a time). BChat picks a random line from your list. Change the list in **Settings → Advanced → Slaps...**: `$nick` is the person you slap.

### What is the Friends List?
Right-click a nick and choose **Add to Friends List**, or type `/notify nick`. **Window → Friends List...** shows which friends are online, for how long, and your note about them.

### Can I keep a note or a sound per friend?
Yes: in **Window → Friends List...**, pick a friend and click **Edit...**. Write a **Note** (it's the same note as in their Address Book card), and choose what happens when they come online or leave: **Show a pop-up**, **Play a sound** (your pop-up sound, or a .wav you pick), **Ask WHOIS**. When they leave, the server tab says how long they were online.

### How do I colour nicks or keep notes about people?
**Settings → Advanced → Nick Colours...** gives nicks colours by rules, and other nicks automatic colours. To keep a note about someone, right-click their nick and choose **Address Book...**; **Window → Address Book...** lists everyone you saved.

### How do I share the song I'm listening to?
First turn it on in **Settings → Preferences → Now Playing**, then type `/np` in a channel. It's off at first, shares only music (no videos), and shows you the line before it's sent. To announce every new song, right-click in a channel and choose **Share → Announce Songs Here**.

### How do I share my PC specs?
Type `/sysinfo` in a channel: one line with Windows, CPU, memory, disks, graphics card and uptime. `/sysinfo -e` shows it only to you. It never includes your PC name, user name or IP address.

### How do I run a command later, or make my own commands?
`/timer 1 60 Back in a minute!` sends that line once after 60 seconds. `/timer news 0 600 /msg #chat Read the news` repeats every 10 minutes until `/timer news off`. `/timers` lists your timers. `/alias hi /say Hello $1!` makes a new command: `/hi Belon` says "Hello Belon!". Use `$1`, `$2-`, `$nick`, `$chan`, `$me`, `$network`, and `|` between commands. `/alias` alone lists yours.

### How do I keep logs of my chats?
Logging is off until you turn it on. **Settings → Preferences → Logging**, tick **Enable logging of conversations to disk**; for one tab only, right-click it and choose **Log to Disk**. The first time, BChat asks once how long to keep logs. **Window → Logs...** opens your logs by network, channel and day, with a search. Logs go to `%APPDATA%\BChat\logs`.

## Notifications and the tray

### How does BChat tell me about new messages?
When BChat isn't the window you're using, a small card appears above the taskbar for **private messages** and when someone **mentions your nick**, with one soft sound. Click the card to jump to that chat. The tray icon blinks too.

It also shows a card when you're **kicked**, when a network **disconnects** (not when you quit yourself), when a **friend comes online**, when someone **invites** you and when someone **offers you a file**. Cards for **notices** are off at first. Change all of these in **Settings → Preferences → Alerts → Also show a pop-up when**.

### Can I change or turn off the notification sound?
**Settings → Preferences → Alerts → Sound with pop-ups**: **Soft chime** (the default), **Bee buzz** or **None**; the play button lets you hear it. It plays at most once every 10 seconds, never during full-screen games or Do Not Disturb, and a sound you picked yourself on the **Sound** page plays instead of it.

### How long do the cards stay?
**Settings → Preferences → Alerts → Keep pop-ups on screen for**: 4, 6 (the default) or 10 seconds, or **Until I close them**. Hovering a card keeps it open.

### Can I stop the notification cards?
Yes: **Settings → Preferences → Alerts**, in the row **Show pop-up notifications on:**, untick what you don't want (channel messages, private messages, highlights).

### Will cards pop up while I'm gaming?
No. BChat stays quiet while Windows says you're busy: full-screen games, presentations, and Focus / Do Not Disturb. Messages still make the tray icon blink.

### What if many messages arrive at once?
BChat never floods your screen. Messages from the same person update one card, at most three cards show, and anything more becomes one summary card ("N more messages from M people").

### How do I keep BChat running in the tray?
**Settings → Preferences → General**, tick **Minimize button sends BChat to the tray** and/or **Close button sends BChat to the tray**. To really quit, right-click the tray icon → **Quit**, or use **BChat → Quit** (`Ctrl+Q`).

### What's in the tray icon's menu?
Right-click the tray icon: **Show BChat**, then your open channels and private chats by network. Bold with a number means unread lines, **@** means someone said your nick. Click one to open BChat right there. Below them: **Away** (sets you away on every network; untick to come back), **Preferences...** and **Quit**. Hovering the tray icon shows how many lines are unread. To open BChat with a double-click instead of one click, or to hide the list, see **Settings → Preferences → Alerts → Tray icon**.

### Can BChat start with Windows?
Yes: **Settings → Preferences → General → Start with Windows**. Next to **When BChat starts**, choose **Minimized** or **In the tray** if you want it to start quietly: in the tray, BChat connects and stays out of sight until you click the tray icon.

---

### I use a bouncer (ZNC, soju). Does BChat know?
Yes. BChat recognises ZNC, soju and psyBNC by what they tell it, and says once in the server tab: "Connected through ZNC (a bouncer)". Hovering the network shows it too, and the quit question reminds you that you stay online there.

When BChat was closed, ZNC plays back what you missed. BChat shows those lines under one grey line, "Played back by ZNC: 12 lines from while BChat was closed", with the times they were really said, and a "Now live" line after them. BChat doesn't also ask the server for history, so nothing shows twice.

### Can BChat rejoin a channel when I'm kicked?
**Settings → Preferences → General**, tick **Rejoin a channel when I'm kicked** (off at first). In the same place, **Show who someone is when they start a private chat with me** (on at first) shows a WhoIs at the top of a new private chat.

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

### Can I log in without a password?
Yes, with a certificate (SASL EXTERNAL), on networks whose services support it (Anope and Atheme do). Open the network's **Edit...** window and set **Log in with:** to **Certificate (SASL EXTERNAL)**:
1. Click **Make New**. BChat makes a certificate on your PC (its private key never leaves your PC).
2. Connect and log in once with your password as usual.
3. Open **Edit...** again and click **Add to NickServ**. NickServ answers in the server tab.

From then on BChat logs you in with the certificate, and no password is stored or sent. It needs an SSL server (a `+` port). You can also use your own certificate with **Choose File...**.

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


### What does SCRAM-SHA-256 mean?
A safer way to log in with SASL. When a network offers it, BChat uses it by itself: your password is never sent, not even on a plain port, and the server has to prove it knows your password too. The server tab says **Logged in as ... with SCRAM-SHA-256**.

### How do I stop BChat flooding or being flooded?
**Settings → Preferences → Flood**. **Pace** sets how fast BChat sends (Careful for slow servers, Fast for your own server or bouncer); your own messages always go before automatic ones. Below that are limits on how often BChat answers CTCP requests (in total and from one person), how many new private chats open a tab, and how many get a WhoIs (0 = never). When a limit is hit, BChat says so once in the server tab. **Back to Normal** resets it.

### Can I lock BChat on a shared or family PC?
Yes: **Settings → Preferences → Lock → Set Password...**. Then BChat asks for the password when it starts, and you can limit it: **No file transfers or direct chats**, **No new private chats** (they show in the server tab), and **Only these channels**. Changing the lock needs the password. Forgot it? Delete `lock.json` in BChat's settings folder: the lock is a house rule, not a safe.

### Can I run BChat from a USB stick?
Yes, in portable mode: start `BChat.exe -portable`, or put an empty file named `portable.txt` next to `BChat.exe`. Settings, logs and downloads then go into a **BChat-data** folder next to the program. Passwords aren't stored in Windows; with a Lock password they are sealed with it, otherwise BChat doesn't keep them.
## Files and direct chats (DCC)

### How do I send someone a file?
Right-click their name → **Send a File**, or type `/dcc send nick`. **Window → File Transfers...** shows every transfer.

### How do I receive a file?
When someone offers a file, it appears in **Window → File Transfers...**. Select it and click **Accept**. Files go to the folder set in **Settings → Preferences → File transfers → Download files to:** (by default `%APPDATA%\BChat\downloads`).

### Why does BChat warn me about some files?
Programs (`.exe`, `.msi`, scripts and similar) can harm your PC, so BChat asks **Accept this file?** first, and never accepts them by itself. Hidden tricks that disguise a program as a picture are removed from the file name. Received files are marked as coming from the internet, so Windows checks them before they run.


### Can BChat accept files from people I trust?
Yes. Right-click someone → **Trust for Files and Chats**, then set **Settings → Preferences → File transfers → Auto accept file offers:** to **From trusted people only**. Their whole address must match (a nick alone never does), and programs still always ask. The trusted list is on the same page.
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
If you registered your nick with NickServ, put the password in the network's **Edit...** window: either **NickServ password:**, or **Log in with: Password (SASL)** with **SASL account:** and **SASL password:**. BChat sends it each time you connect, and keeps it in Windows Credential Manager. To log in without a password, see [Can I log in without a password?](#can-i-log-in-without-a-password).

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
In BChat 0.3.0 and newer: **Help → Report a Problem...**, pick what happened and click **Send**. BChat adds the details for you and hides names and addresses; **See what's sent** shows every word first. After a crash or a freeze, BChat offers this by itself on the next start. You can also ask in **#BChat** on irc.bajubesi.org (people there and the Buzz helper bot can help), in the BChat forum on bajubesi.org, or open an issue on [GitHub](https://github.com/fhazal/BChat/issues).
