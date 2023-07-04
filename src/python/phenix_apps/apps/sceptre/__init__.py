import os
import phenix_apps.apps.sceptre.configs.configs
import phenix_apps.apps.sceptre.protocols

DISABLE_REG_MAP_GEN = os.getenv('PHENIX_APPS_SCEPTRE_DISABLE_REG_MAP', None) != None
