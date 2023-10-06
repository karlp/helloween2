# include default manifest
include("$(PORT_DIR)/boards/manifest.py")

# include our own extra...
module("halloween2.py", base_path="$(BOARD_DIR)/../../src")
module("encoder_portable.py", base_path="$(BOARD_DIR)/../../src")
# Only use this if you're customizing micropython for high speed as well!
#module("tft_config.py", base_path="$(BOARD_DIR)/../../lib/st7789_mpy/examples/configs/tdisplay_esp32")
module("tft_config.py", base_path="$(BOARD_DIR)/../../src")