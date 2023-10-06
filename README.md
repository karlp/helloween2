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


## Upstream
This repository structure is based on: https://github.com/micropython/micropython-example-boards

