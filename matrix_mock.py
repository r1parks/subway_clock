class RGBMatrixOptions:
    def __init__(self):
        self.rows = 32
        self.cols = 64
        self.hardware_mapping = "adafruit-hat"
        self.drop_privileges = False


class RGBMatrix:
    def __init__(self, options=None):
        self.brightness = 100

    def CreateFrameCanvas(self):
        return MockCanvas()

    def Clear(self):
        pass

    def SwapOnVSync(self, canvas):
        return canvas


class MockCanvas:
    def Clear(self):
        pass

    def SetPixel(self, x, y, r, g, b):
        pass


class graphics:
    class Color:
        def __init__(self, r, g, b):
            self.r, self.g, self.b = r, g, b

    class Font:
        def __init__(self):
            pass

        def LoadFont(self, path):
            pass

    @staticmethod
    def DrawText(canvas, font, x, y, color, text):
        pass

    @staticmethod
    def DrawLine(canvas, x1, y1, x2, y2, color):
        pass
