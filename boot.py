# Wird bei jedem Boot ausgefuehrt, bevor main.py startet.
# Absichtlich leer: OTA-Updates laufen jetzt ueber den "Update pruefen"-Button
# im Dashboard (/api/ota/status, /api/ota/apply), nicht mehr automatisch beim
# Booten - das alte Verhalten konnte bei WLAN-Problemen endlos haengen.
