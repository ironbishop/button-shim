import smbus
import time
from threading import Thread
import atexit
from colorsys import hsv_to_rgb

try:
    import queue
except ImportError:
    import Queue as queue

ADDR = 0x3f

__version__ = '0.0.1'

_bus = smbus.SMBus(1)

LED_DATA = 7
LED_CLOCK = 6

REG_INPUT = 0x00
REG_OUTPUT = 0x01
REG_POLARITY = 0x02
REG_CONFIG = 0x03

NUM_BUTTONS = 6

BUTTON_A = 0
"""Button A"""
BUTTON_B = 1
"""Button B"""
BUTTON_C = 2
"""Button C"""
BUTTON_D = 3
"""Button D"""
BUTTON_E = 4
"""Button E"""

NAMES = ['A', 'B', 'C', 'D', 'E']
"""Sometimes you want to print the plain text name of the button that's triggered.

You can use::

    buttonshim.NAMES[button_index]

To accomplish this.

"""

LED_GAMMA = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2,
    2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5,
    6, 6, 6, 7, 7, 7, 8, 8, 8, 9, 9, 9, 10, 10, 11, 11,
    11, 12, 12, 13, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18,
    19, 19, 20, 21, 21, 22, 22, 23, 23, 24, 25, 25, 26, 27, 27, 28,
    29, 29, 30, 31, 31, 32, 33, 34, 34, 35, 36, 37, 37, 38, 39, 40,
    40, 41, 42, 43, 44, 45, 46, 46, 47, 48, 49, 50, 51, 52, 53, 54,
    55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70,
    71, 72, 73, 74, 76, 77, 78, 79, 80, 81, 83, 84, 85, 86, 88, 89,
    90, 91, 93, 94, 95, 96, 98, 99, 100, 102, 103, 104, 106, 107, 109, 110,
    111, 113, 114, 116, 117, 119, 120, 121, 123, 124, 126, 128, 129, 131, 132, 134,
    135, 137, 138, 140, 142, 143, 145, 146, 148, 150, 151, 153, 155, 157, 158, 160,
    162, 163, 165, 167, 169, 170, 172, 174, 176, 178, 179, 181, 183, 185, 187, 189,
    191, 193, 194, 196, 198, 200, 202, 204, 206, 208, 210, 212, 214, 216, 218, 220,
    222, 224, 227, 229, 231, 233, 235, 237, 239, 241, 244, 246, 248, 250, 252, 255]

# The LED is an APA102 driven via the i2c IO expander.
# We must set and clear the Clock and Data pins
# Each byte in _reg_queue represents a snapshot of the pin state

_reg_queue = []
_update_queue = []

_led_queue = queue.Queue()

_t_poll = None

_running = False

_handlers = [[None, None] for x in range(NUM_BUTTONS)]

def _run():
    global _running
    _running = True
    _last_states = 0b00011111

    while _running:
        #print(_led_queue.qsize())
        try:
            led_data = _led_queue.get(False)
            _write(led_data)
            _led_queue.task_done()
        except queue.Empty:
            pass

        states = _bus.read_byte_data(ADDR, REG_INPUT)

        if states != _last_states:
            for x in range(NUM_BUTTONS):
                _last = (_last_states >> x) & 1
                _curr = (states >> x) & 1

                # If _last > _curr then it's a transition from 1 to 0
                # since the buttons are active low, that's a press event
                if _last > _curr and callable(_handlers[x][0]):
                    _handlers[x][0](x, True)
                    continue

                if _last < _curr and callable(_handlers[x][1]):
                    _handlers[x][1](x, False)
                    continue

        _last_states = states

        time.sleep(0.002)

def _quit():
    global _running

    _led_queue.join()
    set_pixel(0, 0, 0)
    _led_queue.join()

    _running = False
    _t_poll.join()

def _init():
    global _t_poll

    _bus.write_byte_data(ADDR, REG_CONFIG, 0b00011111)
    _bus.write_byte_data(ADDR, REG_POLARITY, 0b00000000)
    _bus.write_byte_data(ADDR, REG_OUTPUT, 0b00000000)

    _t_poll = Thread(target=_run)
    _t_poll.daemon = True
    _t_poll.start()

    atexit.register(_quit)

def _set_bit(pin, value):
    global _reg_queue

    if value:
        _reg_queue[-1] |= (1 << pin)
    else:
        _reg_queue[-1] &= ~(1 << pin)

def _next():
    global _reg_queue

    if len(_reg_queue) == 0:
        _reg_queue = [0b00000000]
    else:
        _reg_queue.append(_reg_queue[-1])

def _enqueue():
    global _reg_queue

    _led_queue.put(_reg_queue)

    _reg_queue = []

def _chunk(l, n):
    for i in range(0, len(l)+1, n):
        yield l[i:i + n]

def _write(data):
    for chunk in _chunk(data, 32):
        _bus.write_i2c_block_data(ADDR, REG_OUTPUT, chunk)

def _write_byte(byte):
    for x in range(8):
        _next()
        _set_bit(LED_CLOCK, 0)
        _set_bit(LED_DATA, byte & 0b10000000)
        _next()
        _set_bit(LED_CLOCK, 1)
        byte <<= 1

def on_press(buttons, handler=None):
    """Attach a press handler to one or more buttons.

    This handler is fired when you press a button.

    It will be passed two arguments, the button index and a
    boolean indicating whether the button has been pressed/released::

        @buttonshim.on_press(buttonshim.BUTTON_A)
        def handler(button, pressed):
            # Your code here

    :param buttons: A single button, or a list of buttons
    :param handler: Optional: a function to bind as the handler

    """

    if buttons is None:
        buttons = [BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D, BUTTON_E]

    if isinstance(buttons, int):
        buttons = [buttons]

    def attach_handler(handler):
        for button in buttons:
            _handlers[button][0] = handler

    if handler is not None:
        attach_handler(handler)
    else:
        return attach_handler

def on_release(buttons=None, handler=None):
    """Attach a release handler to one or more buttons.

    This handler is fired when you let go of a button.

    It will be passed two arguments, the button index and a
    boolean indicating whether the button has been pressed/released::

        @buttonshim.on_release(buttonshim.BUTTON_A)
        def handler(button, pressed):
            # Your code here

    :param buttons: A single button, or a list of buttons
    :param handler: Optional: a function to bind as the handler

    """

    if buttons is None:
        buttons = [BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D, BUTTON_E]

    if isinstance(buttons, int):
        buttons = [buttons]

    def attach_handler(handler):
        for button in buttons:
            _handlers[button][1] = handler

    if handler is not None:
        attach_handler(handler)
    else:
        return attach_handler

def set_pixel(r, g, b):
    """Set the Button SHIM RGB pixel

    Display an RGB colour on the Button SHIM pixel.

    :param r: Amount of red, from 0 to 255
    :param g: Amount of green, from 0 to 255
    :param b: Amount of blue, from 0 to 255

    You can use HTML colours directly with hexadecimal notation in Python. EG::

        buttonshim.set_pixel(0xFF, 0x00, 0xFF)

    """

    if not isinstance(r, int) or r < 0 or r > 255:
        raise ValueError("Argument r should be an int from 0 to 255")

    if not isinstance(g, int) or g < 0 or g > 255:
        raise ValueError("Argument g should be an int from 0 to 255")

    if not isinstance(b, int) or b < 0 or b > 255:
        raise ValueError("Argument b should be an int from 0 to 255")

    _write_byte(0)
    _write_byte(0)
    _write_byte(0b11101111)
    _write_byte(LED_GAMMA[b & 0xff])
    _write_byte(LED_GAMMA[g & 0xff])
    _write_byte(LED_GAMMA[r & 0xff])
    _write_byte(0)
    _write_byte(0)
    _enqueue()

_init()

if __name__ == "__main__":
    while True:
        hue = (time.time() * 100 % 360) / 360.0
        r, g, b = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]

        set_pixel(r, g, b)

        @on_press([BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D, BUTTON_E])
        def handle_press(button, state):
            print("PRESS: Button {} ({}) is {}".format(button, NAMES[button], state))

        @on_release([BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D, BUTTON_E])
        def handle_release(button, state):
            print("RELEASE: Button {} ({}) is {}".format(button, NAMES[button], state))

