# Changelog

## 1.0.0

First public release, rewritten from the old private `hassio-amule` add-on.

- aMule 2.3.3 from Debian trixie instead of Alpine's edge/testing package.
- New web UI in the Home Assistant sidebar (Ingress): transfers with progress, search with
  filters and multi-select, uploads, shared files, eD2k/Kad controls, server list and log.
  Works on phones, follows the light/dark theme, English and Spanish.
- Home Assistant integration (HACS) with sensors, connectivity binary sensors, network switches,
  speed limit numbers, bulk buttons, an `amule.add_link` action and download events. Set up
  automatically through Supervisor discovery.
- No more web passwords or PUID/PGID: access goes through Home Assistant, and the EC password
  is generated. Optional remote control for amulegui/amulecmd on port 4712.
- amuled is supervised and restarted if it crashes.
