from tool.browser_driver import PuzzleDriver

a=PuzzleDriver(headless=False)

a.launch()
a.export("./output")