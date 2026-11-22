# aMule

aMule shares and downloads files on the eD2k and Kad networks. Open **aMule** in the sidebar to
search, manage transfers and see the network status.

## Getting a high ID

eD2k gives you a *high ID* when other users can connect to you, and a *low ID* when they can't.
With a low ID you can only download from high ID users, so it is much slower. Kad shows the same
as *firewalled*.

Forward these ports on your router to your Home Assistant machine:

| Port | Protocol | Used for |
| --- | --- | --- |
| 4662 | TCP | eD2k transfers |
| 4672 | UDP | eD2k and Kad |
| 4665 | UDP | eD2k global search (optional) |

Keep the same numbers on both sides: aMule tells the network it listens on these ports. The
**Network** tab of the UI shows your ID and Kad state.

## Options

| Option | Default | Description |
| --- | --- | --- |
| `download_dir` | `/share/amule/incoming` | Finished downloads. Shared on the network. |
| `temp_dir` | `/share/amule/temp` | Unfinished downloads. Needs as much free space as what you download. |
| `share_dirs` | `[]` | Extra folders under `/share` or `/media` to share. |
| `nickname` | `ha-amule` | Name other users see. |
| `max_download_kbps` | `0` | Download limit in kB/s, 0 = unlimited. |
| `max_upload_kbps` | `0` | Upload limit in kB/s, 0 = unlimited. aMule limits your download speed when you upload less than 10 kB/s. |
| `connect_ed2k` | `true` | Connect to eD2k servers on start. |
| `connect_kad` | `true` | Connect to Kad on start. |
| `servers_url` | emule-security `server.met` | Server list loaded on every start. Empty keeps the current list. |
| `nodes_url` | emule-security `nodes.dat` | Kad contacts used the first time. |
| `remote_password` | *(empty)* | Enables remote control from **amulegui** or **amulecmd** on port 4712 (also enable the port under **Network**). |
| `log_level` | `info` | `debug`, `info`, `warning` or `error`. |

Speed limits set from the UI or from Home Assistant last until the app restarts; the options
above are applied on every start.

## Folders

Both folders must be under `/share` or `/media` so you can reach the files from other apps
(Samba, Plex, Jellyfin...). aMule's own state (known files, credits, server list, Kad contacts)
lives in the app's data folder and is part of Home Assistant backups. Unfinished downloads in
`temp_dir` are not.

## Home Assistant integration

Install the **aMule** integration from HACS (see the
[README](https://github.com/jmanera/ha-amule#integration-optional)). Home Assistant discovers the
app by itself and offers to set it up. You get sensors, switches, speed limits, buttons, the
`amule.add_link` action and `amule_download_completed` / `amule_download_failed` events.

## Coming from `hassio-amule`

This is a new app (slug `amule`), so it does not reuse the old add-on's configuration. To keep
unfinished downloads, set `temp_dir` to the old incomplete folder (by default
`/share/incomplete`) and `download_dir` to the old download folder (`/share/downloads`); aMule
picks up the `.part` files on start. Then uninstall the old add-on.

## Privacy and legality

You are responsible for what you download and share. The app shares `download_dir` and
`share_dirs` with the whole network, and everything you download is shared while it downloads.
