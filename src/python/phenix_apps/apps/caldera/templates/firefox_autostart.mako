[Desktop Entry]
Encoding=UTF-8
Version=1.0
Type=Application
Name=Caldera
Comment=Caldera Browser
# HACK: The "Path" option isn't honored on autostart
# (see https://gitlab.xfce.org/xfce/xfce4-session/-/issues/9).
Exec=firefox http://${addr}:8888
OnlyShowIn=XFCE;
StartupNotify=false
Terminal=false
Hidden=false
