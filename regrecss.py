#!/usr/bin/env python3

import argparse
import tempfile
import shutil
import itertools
import time
import sys
import tarfile
import os
import io
from pathlib import Path

from PIL import Image, ImageChops

from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

gui_width = 10
gui_height = 86

# Global variables ftw
current_test = None
all_tests = []
test_index = itertools.count()
snap_count = itertools.count()
environment = {"browser":None, "window":None}


def add_action(action):
    test = all_tests[-1]
    test.queue.append(action)
    return test
def action(action_class):
    environment[action_class.__name__] = action_class
    return action_class


@action
class Test:
    def __init__(self, name=None):
        all_tests.append(self);
        self.index = next(test_index)
        self.name = name or f"test{self.index}"
        self.queue = []
        self.snap_index = itertools.count()
        self.window = None

class Multi:
    def __init__(self, items):
        add_action(self)
        self.items = items
    def __iter__(self):
        return iter(self.items)

@action
class Window:
    def __init__(self, width, height, name=None):
        self.width = width
        self.height = height
        self.name = name or f"{width}x{height}"
    def go(self, driver, test):
        print("window going")
        test.window = self
        driver.set_window_size(self.width + gui_width, self.height + gui_height)
@action
class windows(Multi):
    pass

@action
class url:
    def __init__(self, path):
        add_action(self)
        self.path = path
    def go(self, driver, test):
        driver.get(expand_url(self.path))

@action
class snap:
    def __init__(self, name=None):
        test = add_action(self)
        self.index = next(test.snap_index)
        self.name = name or str(self.index)
    def go(self, driver, test):
        print("kanin")
        window_name = test.window.name if test.window else "default"
        driver.get_screenshot_as_file(f"{next(snap_count)}:{test.name}:{window_name}:{self.index}:.png")

@action
class wait:
    def __init__(self, duration):
        add_action(self)
        self.duration = duration
    def go(self, driver, test):
        time.sleep(self.duration)

@action
class output:
    def __init__(self, message):
        add_action(self)
        self.message = message
    def go(self, driver, test):
        print(self.message)

@action
class await_output:
    def __init__(self, query):
        add_action(self)
        self.query = query
    def go(self, driver, test):
        while True:
            for entry in driver.get_log("browser"):
                if entry["source"] == "console-api":
                    message = entry["message"].split('"', 1)[1][:-1]
                    if message == self.query:
                        return
            time.sleep(0.1)

@action
class resize:
    def __init__(self, width, height):
        add_action(self)
        self.width = width
        self.height = height
    def go(self, driver, test):
        driver.set_window_size(self.width + gui_width, self.height + gui_height)

@action
class await_window_change:
    def __init__(self):
        add_action(self)
    def go(self, driver, test):
        previous = driver.get_window_size()
        while True:
            current = driver.get_window_size()
            if current["width"] != previous["width"] or current["height"] != previous["height"]:
                return
            time.sleep(0.1)

@action
class ensure_window:
    def __init__(self, width=None, height=None):
        add_action(self)
        self.width = width
        self.height = height
    def go(self, driver, test):
        current = driver.get_window_size()
        width = self.width or test.window.width
        height = self.height or test.width.height
        print(f"Actual window {current['width']} x {current['height']}")
        if current["width"] + gui_width != width or current["height"] + gui_height != height:
            pass
            # sys.exit(-1)


def ensure_correctness():
    # if len(all_windows) == 0:
    #     print("Error in config. No windows defined")
    if len(all_tests) == 0:
        print("Error in config. No tests defined")
    # if not ensure_unique_names(all_windows):
    #     print("Error in config file. Windows with identical names")
    if not ensure_unique_names(all_tests):
        print("Error in config file. Tests with identical names")

def ensure_unique_names(items):
    unique = set(item.name for item in items)
    return len(unique) == len(items)

def expand_url(initial):
    if not initial.startswith("http"):
        return "http://" + initial
    return initial

def create_test_suite(config):
    current_directory = Path(".").absolute()
    config = config.absolute()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        shutil.copyfile(config, "config.py")
        execute_tests(config)
        with tarfile.open(current_directory / "testsuite.regrecss", "w") as tar:
            for name in Path(".").iterdir():
                tar.add(name)

def execute_test_suite(testsuite):
    current_directory = Path(".").absolute()
    testsuite = testsuite.absolute()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        with tarfile.open(testsuite) as tar:
            config_infos = set()
            image_infos = list()
            for tarinfo in tar:
                if tarinfo.name.endswith(".py"):
                    config_infos.add(tarinfo)
                elif tarinfo.name.endswith(".png"):
                    image_infos.append(tarinfo)
                else:
                    print("ERROR: Unknown filetype", tarinfo.name)
                    sys.exit(-1)
            for tarinfo in config_infos:
                fileobj = tar.extractfile(tarinfo)
                execute_tests(fileobj.read())

            base_names = set(tarinfo.name for tarinfo in image_infos)
            new_names = set(path.name for path in Path(".").glob("*.png"))
            if len(base_names) != len(new_names) or not all(name in new_names for name in base_names):
                print("ERROR: There are unexpected inconsistencies between the testsuites image set and the newly created")
                sys.exit(-1)

            results = []
            for tarinfo in image_infos:
                print(tarinfo.name)
                fileobj = tar.extractfile(tarinfo)
                byteio = io.BytesIO(fileobj.read())
                base_image = Image.open(byteio)
                new_image = Image.open(tarinfo.name)
                comparison = Comparison(tarinfo.name, base_image, new_image)
                results.append(comparison)
    os.chdir(current_directory)
    report(results)

def report(comparisons):
    comparisons.sort(key=lambda c: c.index)
    failed = 0
    for comparison in comparisons:
        if comparison.changed != 0:
            failed += 1
            percentage = comparison.changed / (comparison.changed + comparison.unchanged) * 100
            print(f"Test {comparison.index} failed! Test {comparison.test}:{comparison.snap} {comparison.window} differs by {percentage:.1f}%")
            comparison.image.save(comparison.description)
    if failed:
        print(f"{failed} out of {len(comparisons)} tests failed!")
    else:
        print(f"{len(comparisons)} tests completed successfully.")


class Comparison:
    def __init__(self, description, base, new):
        self.description = description
        index, test, window, snap, _ = description.split(":")
        self.index = int(index)
        self.test = test
        self.window = window
        self.snap = int(snap)
        self.image = None

        if base.size != new.size:
            print("ERROR: There are unexpected inconsistencies in the sizes between the images")
            sys.exit(-1)
        table = [0] + [255]*255
        difference = ImageChops.difference(base, new)
        mask = difference.convert("L").point(table)
        histogram = mask.histogram()
        self.unchanged, self.changed = histogram[0], histogram[-1]
        if self.changed != 0:
            red = Image.new("RGB", base.size, "#ff0000")
            base.paste(red, mask=mask)
            self.image = base





def execute_tests(config):
    """Run the python script to generate pictures"""
    if isinstance(config, Path):
        with open(config) as config_file:
            config_content = config_file.read()
    else:
        config_content = config
    exec(config_content, environment)
    ensure_correctness()
    for test in all_tests:
        options = webdriver.ChromeOptions()
        options.add_argument("disable-infobars")
        # options.add_argument(f"window-size={window.width}x{window.height}")
        desired = DesiredCapabilities.CHROME
        desired ['loggingPrefs'] = { 'browser':'ALL' }
        driver = webdriver.Chrome(chrome_options=options, desired_capabilities=desired)
        recurse(driver, test, 0)
        driver.quit()
def recurse(driver, test, index):
    if index >= len(test.queue):
        return
    action = test.queue[index]
    print(">>>", action.__class__.__name__)
    if isinstance(action, Multi):
        print("is multi")
        for instance in action:
            instance.go(driver, test)
            recurse(driver, test, index+1)
    else:
        action.go(driver, test)
        recurse(driver, test, index+1)



def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", help="Create a new test suite from a config to test against", default=None)
    group.add_argument("--test", help="Test against a testsuite", default=None)
    args = parser.parse_args()

    if args.create:
        create_test_suite(Path(args.create))
    elif args.test:
        execute_test_suite(Path(args.test))

    sys.exit(1)

if __name__ == "__main__":
    main()
