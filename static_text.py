#!/usr/bin/env python3
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# 1. Set up the hardware configuration
options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.hardware_mapping = 'adafruit-hat'
# options.brightness = 50  # Uncomment to dim the screen if it's too bright!

options.drop_privileges = False

# 2. Initialize the matrix
matrix = RGBMatrix(options=options)

# 3. Create the off-screen canvas (the "back buffer")
canvas = matrix.CreateFrameCanvas()

# 4. Load a font (using a relative path to the font folder)
font_path = "/home/robert/rpi-rgb-led-matrix/fonts/7x13.bdf"
font = graphics.Font()
font.LoadFont(font_path)

# 5. Define a text color (R, G, B)
text_color = graphics.Color(255, 153, 51) # MTA Orange for the F train!

# 6. Draw the text to the hidden canvas
# The coordinates (x, y) represent the baseline of the text. 
# y=13 means the bottom of the letters will rest on the 13th row of pixels.
graphics.DrawText(canvas, font, 2, 13, text_color, "Hello,")
graphics.DrawText(canvas, font, 2, 28, text_color, "World!")

# 7. Swap the hidden canvas to the actual display
canvas = matrix.SwapOnVSync(canvas)

print("Displaying static text. Press Ctrl+C to exit.")

# 8. Keep the script alive. If the script exits, the matrix clears.
try:
    while True:
        time.sleep(100)
except KeyboardInterrupt:
    import sys
    sys.exit(0)
