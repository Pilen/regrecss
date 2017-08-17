#!/usr/bin/env python3

import argparse
import base64
import io
import itertools
import math
import os
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageChops

from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

gui_width = 10
gui_height = 86

# Global variables ftw
current_test = None
directory = None
all_tests = []
test_index = itertools.count()
snap_count = itertools.count()
environment = {}


def action(action):
    environment[action.__name__] = action
    return action

################################################################################
#                                   Actions                                    #
################################################################################
@action
class Test:
    def __init__(self, name=None):
        all_tests.append(self)
        global current_test
        self.index = next(test_index)
        self.name = name or f"test{self.index}"
        self.snap_index = itertools.count()

        if current_test != None:
            current_test.browser.quit()
        current_test = self

        options = webdriver.ChromeOptions()
        options.add_argument("disable-infobars")
        # options.add_argument(f"window-size={window.width}x{window.height}")
        desired = DesiredCapabilities.CHROME
        desired ['loggingPrefs'] = { 'browser':'ALL' }
        self.browser = webdriver.Chrome(chrome_options=options, desired_capabilities=desired)
        current = current_test.browser.get_window_size()
        self.window = Window(current["width"], current["height"], "default")


@action
class Window:
    def __init__(self, width, height, name=None):
        self.width = width
        self.height = height
        self.name = name or f"{width}x{height}"
    def resize(self):
        current_test.window = self
        current_test.browser.set_window_size(self.width + gui_width,
                                            self.height + gui_height)

@action
def url(path):
    current_test.browser.get(expand_url(path))

@action
def snap(name=None):
    index = next(current_test.snap_index)
    name = name or str(index)
    window_name = current_test.window.name if current_test.window else "default"
    current_test.browser.get_screenshot_as_file(directory / f"{next(snap_count)}:{current_test.name}:{window_name}:{index}:.png")

@action
def wait(duration):
    time.sleep(duration)

@action
def await_output(query):
    while True:
        for entry in current_test.browser.get_log("browser"):
            if entry["source"] == "console-api":
                message = entry["message"].split('"', 1)[1][:-1]
                if message == query:
                    return
        time.sleep(0.1)

@action
def resize(a, b=None):
    if isintance(a, Window) and b == None:
        a.resize()
    else:
        Window(a, b).resize()
@action
def await_window_change():
    print("Awaiting window change...")
    # previous = current_test.browser.get_window_size()
    previous = {"width": current_test.window.width, "height":current_test.window.height}
    while True:
        current = current_test.browser.get_window_size()
        if "width" not in current or "height" not in current:
            print("Browser quit unexpectedly")
            sys.exit(-1)
        if current["width"] != previous["width"] or current["height"] != previous["height"]:
            return
        time.sleep(0.1)

@action
def ensure_window(width=None, height=None):
    if isintance(a, Window) and b == None:
        width = a.width
        height = a.height
    else:
        width = width or test.window.width
        height = height or test.width.height
    current = current_test.browser.get_window_size()
    if current["width"] + gui_width != width or current["height"] + gui_height != height:
        print("Dimensions does not match")
        sys.exit(-1)

@action
def get_browser():
    return current_test.browser

################################################################################
#                                  Utilities                                   #
################################################################################

def ensure_unique_names(items):
    unique = set(item.name for item in items)
    return len(unique) == len(items)

def expand_url(initial):
    if not initial.startswith("http"):
        return "http://" + initial
    return initial


################################################################################
#                                  Reporting                                   #
################################################################################

def console_report(comparisons):
    failed = 0
    for comparison in comparisons:
        if comparison.changed != 0:
            failed += 1
            print(f"Test {comparison.index} failed! Test {comparison.test}:{comparison.snap} {comparison.window} differs by {comparison.unchanged}px = {comparison.percentage:.1f}%")
    if failed:
        print(f"{failed} out of {len(comparisons)} tests failed!")
    else:
        print(f"{len(comparisons)} tests completed successfully.")

def html_report(comparisons):
    def encode(img):
        output = io.BytesIO()
        img.save(output, format="PNG")
        output.seek(0)
        output_s = output.read()
        b64 = base64.b64encode(output_s)
        return str(b64)[2:-1]

    failed = len([comp for comp in comparisons if comp.changed != 0])
    html = [html_head]
    for index, comparison in enumerate(comparisons):
        if comparison.changed != 0:
            error = encode(comparison.error)
            base = encode(comparison.base)
            new = encode(comparison.new)
            entry = html_entry.format(index=index, comparison=comparison, error=error, base=base, new=new)
            html.append(entry)
    html.append(html_end)
    with open("report.html", "w") as file:
        file.write("\n".join(html))


html_head = """
<!DOCTYPE html>
<html>
  <head>
    <title>regrecss report</title>
    <script>
      function show(index, selected) {
          parent = document.querySelector("#_"+index);
          images = parent.children;
          for (var i = 0; i < images.length; i++) {
              images[i].style.display = "none";
          }
          image = document.querySelector("#_"+index+" ."+selected);
          image.style.display = "initial";
      }
    </script>
  </head>
"""
html_entry = """
  <h1>Test failed</h1>
  <p>
    File: Unknown<br/>
    Line: Unknown<br/>
    Window: {comparison.window}
  </p>
  <button onclick="show({index}, 'error')">Error</button>
  <button onclick="show({index}, 'base')">Base</button>
  <button onclick="show({index}, 'new')">New</button>
  <div id="_{index}">
  <img class="error"
       src="data:image/png;base64,{error}"
       style="display: initial"/>
  <img class="base"
       src="data:image/png;base64,{base}"
       style="display: none"/>
  <img class="new"
       src="data:image/png;base64,{new}"
       style="display: none"/>
  </div>
"""
html_end = """
</html>
"""


################################################################################
#                                  Main flow                                   #
################################################################################

class Comparison:
    def __init__(self, description, base, new):
        self.description = description
        index, test, window, snap, _ = description.split(":")
        self.index = int(index)
        self.test = test
        self.window = window
        self.snap = int(snap)
        self.error = None
        self.base = None
        self.new = None

        if base.size != new.size:
            print("ERROR: There are unexpected inconsistencies in the sizes between the images")
            sys.exit(-1)
        table = [0] + [255]*255
        error = base.copy()
        difference = ImageChops.difference(base, new)
        mask = difference.convert("L").point(table)
        histogram = mask.histogram()
        self.unchanged, self.changed = histogram[0], histogram[-1]
        if self.changed != 0:
            percentage = self.changed / (self.changed + self.unchanged) * 100
            percentage = math.ceil((percentage * 10)) / 10 # Round up
            self.percentage = percentage

            color = Image.new("RGB", base.size, "#ff00ff")
            error.paste(color, mask=mask)
            self.error = error
            self.base = base
            self.new = new


def execute_tests(config):
    """Run the python script to generate pictures"""
    if isinstance(config, Path):
        with open(config) as config_file:
            config_content = config_file.read()
    else:
        config_content = config
    exec(config_content, environment)
    if current_test == None:
        print("No tests in testsuite")
        sys.exit(-1)
    current_test.browser.quit()
    if not ensure_unique_names(all_tests):
        print("Error in config file. Tests with identical names")
        sys.exit(-1)

def create_test_suite(testsuite, configs):
    testsuite = Path(testsuite).absolute()
    configs = [Path(config).absolute() for config in configs]
    os.chdir(testsuite.parent)
    with tempfile.TemporaryDirectory() as tmpdir:
        global directory
        directory = Path(tmpdir)
        for i, config in enumerate(configs):
            new_name = "{}.py".format(i)
            shutil.copyfile(config, directory/new_name)
            execute_tests(config)
        with tarfile.open(testsuite, "w") as tar:
            for path in directory.iterdir():
                tar.add(path, arcname=Path("testsuite_DO_NOT_MODIFY")/path.name)

def execute_test_suite(testsuite):
    testsuite = Path(testsuite).absolute()
    os.chdir(testsuite.parent)
    with tempfile.TemporaryDirectory() as tmpdir:
        global directory
        directory = Path(tmpdir)
        with tarfile.open(testsuite) as tar:
            config_infos = list()
            image_infos = list()
            for tarinfo in tar:
                name = tarinfo.name.split("/")[1]
                tarinfo.name = name
                if tarinfo.name.endswith(".py"):
                    config_infos.append(tarinfo)
                elif tarinfo.name.endswith(".png"):
                    image_infos.append(tarinfo)
                else:
                    print("ERROR: Unknown filetype", tarinfo.name)
                    sys.exit(-1)

            config_infos.sort(key=lambda c: int(c.name.split(".")[0]))

            for tarinfo in config_infos:
                fileobj = tar.extractfile(tarinfo)
                execute_tests(fileobj.read())

            base_names = set(tarinfo.name for tarinfo in image_infos)
            new_names = set(path.name for path in directory.glob("*.png"))
            if len(base_names) != len(new_names) or not all(name in new_names for name in base_names):
                print("ERROR: There are unexpected inconsistencies between the testsuites image set and the newly created")
                sys.exit(-1)

            results = []
            for tarinfo in image_infos:
                fileobj = tar.extractfile(tarinfo)
                byteio = io.BytesIO(fileobj.read())
                base_image = Image.open(byteio)
                new_image = Image.open(directory / tarinfo.name)
                comparison = Comparison(tarinfo.name, base_image, new_image)
                results.append(comparison)
    results.sort(key=lambda c: c.index)
    console_report(results)
    html_report(results)


################################################################################
#                                     Main                                     #
################################################################################

def main():
    parser = argparse.ArgumentParser(description="A tool for regression testing webpages/CSS", add_help=False)
    # group = parser.add_mutually_exclusive_group(required=True)
    # group.add_argument("--create", help="Create a new test suite from a config to test against", default=None)
    # group.add_argument("--test", help="Test against a testsuite", default=None)
    parser.add_argument("-h", "--help", action="store_true")
    subparsers = parser.add_subparsers(dest="subcommand")
    parser_create = subparsers.add_parser("create", help="Create a new testsuite", add_help=False)
    parser_create.add_argument("testsuite", help="filename for the testsuite")
    parser_create.add_argument("config", nargs="+", help="Config file[s] to use in the testsuite")

    parser_test = subparsers.add_parser("test", help="Test using an existing testsuite", add_help=False)
    parser_test.add_argument("testsuite", help="The testsuite to execute")

    def help():
        print(parser.format_help())
        print("\n#### create ####")
        print(parser_create.format_help())
        print("\n#### test ####")
        print(parser_test.format_help())

    args = parser.parse_args()

    if args.help or args.subcommand == None:
        help()
    elif args.subcommand == "create":
        create_test_suite(Path(args.testsuite), [Path(config) for config in args.config])
    elif args.subcommand == "test":
        execute_test_suite(Path(args.testsuite))
    else:
        assert False
    sys.exit(1)

if __name__ == "__main__":
    main()
