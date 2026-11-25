---
id: n-be14eebc0c
kind: fact
at: 2026-11-25T20:58:44Z
source: agent
evidence:
  - Lab 2/Q4/src/serial.cpp
  - Lab 2/Q4/src/main.c
  - Lab 2/Q4/platformio.ini
  - Lab 2/Q4_group_idle_hook/src/board.cpp
  - Lab 2/Q2/src/serial.c
evidence_sha:
  - Lab 2/Q4/src/serial.cpp=ac04eb49ac47
  - Lab 2/Q4/src/main.c=ca9a9e2371ad
  - Lab 2/Q4/platformio.ini=a74b8567e86b
  - Lab 2/Q4_group_idle_hook/src/board.cpp=0a7a8cb4fe8b
  - Lab 2/Q2/src/serial.c=8270f2ba2bd9
checked: holds
checked_at: 2026-11-25T20:58:49Z
checked_why: Lab 2/Q2/src/serial.c:2-45 is a SERCOM5 UART with no USB code, main.c:109 calls serial_init; Lab 2/Q4/src/serial.cpp:19-22 and Q4_group_idle_hook/src/board.cpp:18-25 do init/__libc_init_array/USBDevice; lib_deps ^2.3.0
checked_sha: 56c450293e57
replaces: n-e31ac52285
---

ECNG3006 FreeRTOS labs keep the course template's main() and repair serial by hand; lib_deps briscoetech/FreeRTOS_SAMD21 @ ^2.3.0 (Lab 2 Q2-Q4, lab1 Question 7).
Overriding main() skips the Arduino core's startup, so SerialUSB is dead until the board is brought up by hand. Most projects do that in a small C++ file called first from main(): init(); __libc_init_array(); USBDevice.init(); USBDevice.attach(); (Lab 2/Q3, Q4 and Lab 3/Q2, Q3 src/serial.cpp; Lab 2/Q4_group_idle_hook/src/board.cpp, which sets pin directions after init() because init() resets pins). main() then creates the tasks and calls vTaskStartScheduler().
Lab 2/Q2 is the exception: no USB at all. Its src/serial.c is a bare-metal UART on SERCOM5 (pins 13 RX / 14 TX, 115200 8N1), so output needs a 3.3 V USB-TTL adapter on pin 14, not the board's USB port.
The labs do not use the library's setup()/loop() style. vApplicationIdleHook is defined only where the question asks for it (Lab 2/Q4, Q4_group_idle_hook).
