## What?
Happy halloween 2023... If this gets finished, it might be worth more documentation

## Getting Started
```
. /esp/somewhere/export.sh
git submodule update --init
make -C lib/micropython/ports/esp32 submodules
cd boards/CUSTOM_ESP32
idf.py build
....
profit
```
aka
```
podman run --rm --device /dev/ttyUSB1 -v .:/project -w /project/boards/CUSTOM_ESP32 -e HOME=/tmp espressif/idf:v5.0.4 idf.py -b 921660 build erase-flash flash
```


## Upstream
This repository structure is based on: https://github.com/micropython/micropython-example-boards

