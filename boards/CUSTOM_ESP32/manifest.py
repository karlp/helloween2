# include default manifest
include("$(PORT_DIR)/boards/manifest.py")

# include our own extra...
module("halloween2.py", base_path="$(BOARD_DIR)/../../src")
module("spider2.py", base_path="$(BOARD_DIR)/../../src")
module("encoder_portable.py", base_path="$(BOARD_DIR)/../../src")
module("mp_neopixel.py", base_path="$(BOARD_DIR)/../../src")
# Only use this if you're customizing micropython for high speed as well!
#module("tft_config.py", base_path="$(BOARD_DIR)/../../lib/st7789_mpy/examples/configs/tdisplay_esp32")
module("tft_config.py", base_path="$(BOARD_DIR)/../../src")

# Add as many as you feel you need
module("vga1_16x16.py", base_path="$(BOARD_DIR)/../../lib/st7789_mpy/fonts/bitmap")
module("vga1_8x8.py", base_path="$(BOARD_DIR)/../../lib/st7789_mpy/fonts/bitmap")

module("mqtt_as.py", base_path="$(BOARD_DIR)/../../lib/micropython-mqtt/mqtt_as")

package("prometheus_express", base_path="$(BOARD_DIR)/../../lib/prometheus_express_aio")