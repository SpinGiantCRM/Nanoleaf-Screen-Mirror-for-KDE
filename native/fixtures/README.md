# Native regression fixtures

These checked-in reference vectors remain in use by Rust tests after Python
retirement. They cover complete colour/calibration arithmetic, geometry,
blending, highlight policies, palettes and HID protocol encoding. Keep them as
independent regression inputs; do not regenerate expected results from the code
being tested. Original Python generators and oracle implementation are retained
at Git commit `85f59888d373667f48651f8cbb2333b8605bfbc5`.
